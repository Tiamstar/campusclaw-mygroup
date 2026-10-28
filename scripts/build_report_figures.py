"""Combine paired, unaltered browser screenshots for the acceptance report."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"
FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"


def pair(left_name, right_name, labels, output_name):
    left = Image.open(EVIDENCE / left_name).convert("RGB")
    right = Image.open(EVIDENCE / right_name).convert("RGB")
    gap, margin, heading = 26, 20, 58
    width = left.width + right.width + gap + margin * 2
    height = max(left.height, right.height) + margin * 2 + heading
    canvas = Image.new("RGB", (width, height), "#f4f5f6")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(FONT, 18)
    left_x, right_x = margin, margin + left.width + gap
    draw.text((left_x, margin), labels[0], font=font, fill="#8b1a1a")
    draw.text((right_x, margin), labels[1], font=font, fill="#8b1a1a")
    canvas.paste(left, (left_x, heading))
    canvas.paste(right, (right_x, heading))
    canvas.save(EVIDENCE / output_name)
    print(output_name)


if __name__ == "__main__":
    pair("03-prompt-template.png", "04a-skill-upload-example.png",
         ("教师维护提示词模板", "教师选择 Markdown 技能文件"), "03-configured-prompt-and-upload.png")
    pair("09-mcp-discovery-audit.png", "13-mcp-denied-audit.png",
         ("连接：发现工具并记录 ok", "断开：调用记录 denied"), "09-mcp-connected-vs-denied.png")
