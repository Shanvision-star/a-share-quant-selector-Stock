"""
简单的本地触发器：读取 .superpowers/skills/full-dev-workflow.skill.yaml 并打印《开发前说明》和《开发后总结》部分，便于手动验证 Skill 的 prompt 内容。
用法: python scripts\trigger_full_dev_workflow.py
"""
import sys
from pathlib import Path

skill_path = Path(__file__).resolve().parents[1] / '.superpowers' / 'skills' / 'full-dev-workflow.skill.yaml'
if not skill_path.exists():
    print(f"Skill 文件未找到: {skill_path}")
    sys.exit(1)

with open(skill_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到 prompt: | 并打印后面的块
prompt_start = None
for i, ln in enumerate(lines):
    if ln.strip() == 'prompt: |':
        prompt_start = i+1
        break

if prompt_start is None:
    print('未找到 prompt 部分')
    sys.exit(1)

# 收集 prompt 区块（直到文件末尾）
prompt_block = ''.join(lines[prompt_start:])
print('\n--- full-dev-workflow prompt start ---\n')
print(prompt_block)
print('\n--- full-dev-workflow prompt end ---\n')
print('验证步骤示例：')
print('1) 启动 copilot（在仓库根目录），确认 /skills 列表包含 full-dev-workflow')
print('2) 在 copilot 会话中发出代码生成或修改请求，skill 应在生成前输出《开发前说明》，操作后输出《开发后总结》')
