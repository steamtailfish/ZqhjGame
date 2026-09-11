"""Read a DOCX without Office; preserve body order, tables and original media."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def text_of(element):
    parts = []
    for item in element.iter():
        local = item.tag.rsplit("}", 1)[-1]
        if local in {"t", "delText"} and item.text:
            parts.append(item.text)
        elif local == "tab":
            parts.append("\t")
        elif local in {"br", "cr"}:
            parts.append("\n")
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "docs" / "manual")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    media_dir = args.output / "media"
    media_dir.mkdir(exist_ok=True)
    records, images, extras = [], [], []
    with ZipFile(args.source) as archive:
        relroot = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in relroot}
        root = ET.fromstring(archive.read("word/document.xml"))
        body = root.find("w:body", NS)
        lines = ["# 参赛手册完整 OOXML 内容提取", "",
                 "定位使用正文块 Bxxxx、表 Txxx、行 Rxxx；不是 Word 页码。原文件未修改。", ""]
        table_number = 0
        for number, item in enumerate(body, 1):
            tag = item.tag.rsplit("}", 1)[-1]
            key = f"B{number:04d}"
            record = {"id": key, "kind": tag, "text": text_of(item)}
            if tag == "tbl":
                table_number += 1
                table_id = f"T{table_number:03d}"
                record["table_id"] = table_id
                record["rows"] = []
                lines.append(f"## [{key} / {table_id}] 表格")
                for rn, row in enumerate(item.findall("w:tr", NS), 1):
                    cells = [text_of(cell) for cell in row.findall("w:tc", NS)]
                    record["rows"].append(cells)
                    lines.append(f"[{table_id}/R{rn:03d}] " + " | ".join(c.replace("\n", " / ") for c in cells))
            else:
                lines.append(f"[{key}] {record['text']}")
            embedded = []
            for blip in item.findall(".//a:blip", NS):
                rid = blip.get(f"{{{NS['r']}}}embed") or blip.get(f"{{{NS['r']}}}link")
                embedded.append({"relationship": rid, "target": rels.get(rid)})
            record["images"] = embedded
            for entry in embedded:
                lines.append(f"图片: {entry['target']} ({entry['relationship']})")
            records.append(record)
            lines.append("")
        for name in archive.namelist():
            if name.startswith("word/media/") and not name.endswith("/"):
                data = archive.read(name)
                (media_dir / Path(name).name).write_bytes(data)
                images.append({"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            elif name.startswith("word/") and name.endswith(".xml") and any(s in name for s in ("header", "footer", "footnotes", "endnotes", "comments")):
                value = text_of(ET.fromstring(archive.read(name)))
                extras.append({"part": name, "text": value})
                lines.extend([f"## 附加 XML {name}", value, ""])
        manifest = {"source_name": args.source.name,
                    "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
                    "blocks": len(records), "tables": table_number, "media": images,
                    "auxiliary_parts": extras,
                    "embedded_objects": [n for n in archive.namelist() if n.startswith("word/embeddings/")],
                    "revision_counts": {key: len(root.findall(f".//w:{key}", NS)) for key in ("ins", "del")},
                    "limitations": ["XML extraction does not verify pagination/layout or OCR image content; inspect media separately."]}
        (args.output / "MANUAL_EXTRACT.md").write_text("\n".join(lines), encoding="utf-8")
        (args.output / "body.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
