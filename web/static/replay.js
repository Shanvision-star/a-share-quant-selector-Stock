/**
 * 复盘图示页面 JavaScript
 * 支持粘贴 (Ctrl+V) 和拖拽上传 K 线图片
 */

const dropArea = document.getElementById('drop-area');
const gallery = document.getElementById('gallery');

// ---- 拖拽 ----
dropArea.addEventListener('dragover', e => {
    e.preventDefault();
    dropArea.classList.add('drag-over');
});

dropArea.addEventListener('dragleave', () => {
    dropArea.classList.remove('drag-over');
});

dropArea.addEventListener('drop', e => {
    e.preventDefault();
    dropArea.classList.remove('drag-over');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        uploadFile(files[0]);
    }
});

// ---- 粘贴 ----
document.addEventListener('paste', e => {
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (const item of items) {
        if (item.type.startsWith('image/')) {
            const file = item.getAsFile();
            if (file) uploadFile(file);
            break;
        }
    }
});

// ---- 点击区域弹出文件选择 ----
dropArea.addEventListener('click', () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = () => {
        if (input.files.length > 0) uploadFile(input.files[0]);
    };
    input.click();
});

// ---- 上传逻辑 ----
async function uploadFile(file) {
    const formData = new FormData();
    formData.append('image', file, file.name || 'image.png');

    try {
        const res = await fetch('/api/replay/upload', { method: 'POST', body: formData });
        const result = await res.json();
        if (result.success) {
            addToGallery(result.url, file.name || 'image.png');
        } else {
            alert('上传失败：' + result.error);
        }
    } catch (err) {
        alert('上传失败：' + err.message);
    }
}

function addToGallery(url, name) {
    const item = document.createElement('div');
    item.className = 'gallery-item';

    const img = document.createElement('img');
    img.src = url;
    img.alt = name;
    img.loading = 'lazy';

    const footer = document.createElement('div');
    footer.className = 'gallery-item-footer';

    const nameSpan = document.createElement('span');
    nameSpan.textContent = name;

    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.textContent = '查看原图';

    footer.appendChild(nameSpan);
    footer.appendChild(link);
    item.appendChild(img);
    item.appendChild(footer);
    gallery.prepend(item);
}
