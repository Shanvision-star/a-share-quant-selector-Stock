import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReviewAttachmentUploader from '@/components/ReviewAttachmentUploader.vue'

const uploadReviewAttachment = vi.hoisted(() => vi.fn())

vi.mock('@/api/reviews', () => ({ uploadReviewAttachment }))
enableAutoUnmount(afterEach)

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

function pasteEvent(files: File[]): Event {
  const event = new Event('paste', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'clipboardData', { value: { files } })
  return event
}

describe('ReviewAttachmentUploader', () => {
  afterEach(() => {
    uploadReviewAttachment.mockReset()
    document.body.innerHTML = ''
  })

  it('freezes date and identity for a batch and skips stale markdown insertion', async () => {
    const first = deferred<any>()
    const second = deferred<any>()
    uploadReviewAttachment
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
    const insertMarkdown = vi.fn()
    const wrapper = mount(ReviewAttachmentUploader, {
      global: { stubs: { 'el-icon': true } },
      props: {
        reviewDate: '2026-07-11',
        documentIdentity: 'document-1',
        insertMarkdown,
      },
    })
    const files = [
      new File(['a'], 'a.png', { type: 'image/png' }),
      new File(['b'], 'b.png', { type: 'image/png' }),
    ]

    const upload = (wrapper.vm as any).uploadFiles(files)
    await flushPromises()
    expect(uploadReviewAttachment).toHaveBeenNthCalledWith(1, '2026-07-11', files[0])

    await wrapper.setProps({ reviewDate: '2026-07-12', documentIdentity: 'document-2' })
    first.resolve({ data: { data: { markdown: '![a](a.png)' } } })
    await flushPromises()
    expect(uploadReviewAttachment).toHaveBeenNthCalledWith(2, '2026-07-11', files[1])

    second.resolve({ data: { data: { markdown: '![b](b.png)' } } })
    await upload
    expect(insertMarkdown).not.toHaveBeenCalled()
    expect(wrapper.emitted('pending-change')).toEqual([[true], [false]])
  })

  it('handles paste only on its explicit paste zone', async () => {
    uploadReviewAttachment.mockResolvedValue({ data: { data: { markdown: '![a](a.png)' } } })
    const insertMarkdown = vi.fn()
    const wrapper = mount(ReviewAttachmentUploader, {
      attachTo: document.body,
      global: { stubs: { 'el-icon': true } },
      props: {
        reviewDate: '2026-07-11',
        documentIdentity: 'document-1',
        insertMarkdown,
      },
    })
    const image = new File(['a'], 'a.png', { type: 'image/png' })
    const titleInput = document.createElement('input')
    document.body.appendChild(titleInput)

    titleInput.dispatchEvent(pasteEvent([image]))
    await flushPromises()
    expect(uploadReviewAttachment).not.toHaveBeenCalled()

    wrapper.get('.upload-dropzone').element.dispatchEvent(pasteEvent([image]))
    await flushPromises()
    expect(uploadReviewAttachment).toHaveBeenCalledTimes(1)
    expect(insertMarkdown).toHaveBeenCalledWith('![a](a.png)', {
      reviewDate: '2026-07-11',
      documentIdentity: 'document-1',
    })
  })
})
