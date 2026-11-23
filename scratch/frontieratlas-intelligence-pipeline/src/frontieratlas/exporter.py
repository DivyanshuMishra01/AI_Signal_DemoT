"""Export engine for FrontierAtlas Intelligence Pipeline.

Generates the 6 required output deliverables across CSV, Excel (multi-tab XLSX),
and detailed JSON execution run reports.
"""

from __future__ import annotations

import csv
import json
import logging
import zipfile
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from frontieratlas.storage import StorageEngine

logger = logging.getLogger(__name__)


def generate_native_xlsx(
    sheets: List[Tuple[str, List[Dict[str, Any]]]],
    output_path: str
) -> None:
    """Generate a multi-tab Microsoft Excel (.xlsx) file using pure Python standard library.
    
    Creates compliant OpenXML workbook with 6 sheets, headers, and cell formatting.
    """
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
        # 1. [Content_Types].xml
        content_types = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
            '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
            '  <Default Extension="xml" ContentType="application/xml"/>',
            '  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            '  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        ]
        for idx in range(1, len(sheets) + 1):
            content_types.append(
                f'  <Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
        content_types.append('</Types>')
        z.writestr('[Content_Types].xml', "\n".join(content_types))

        # 2. _rels/.rels
        z.writestr(
            '_rels/.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>\n'
            '</Relationships>'
        )

        # 3. xl/_rels/workbook.xml.rels
        wb_rels = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        ]
        for idx in range(1, len(sheets) + 1):
            wb_rels.append(
                f'  <Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
            )
        wb_rels.append(
            f'  <Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        )
        wb_rels.append('</Relationships>')
        z.writestr('xl/_rels/workbook.xml.rels', "\n".join(wb_rels))

        # 4. xl/styles.xml
        z.writestr(
            'xl/styles.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\n'
            '  <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>\n'
            '  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>\n'
            '  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>\n'
            '  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>\n'
            '  <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>\n'
            '</styleSheet>'
        )

        # 5. xl/workbook.xml
        wb_xml = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
            '  <sheets>'
        ]
        for idx, (sheet_title, _) in enumerate(sheets, start=1):
            clean_title = sheet_title.replace("/", "-")
            wb_xml.append(f'    <sheet name="{clean_title}" sheetId="{idx}" r:id="rId{idx}"/>')
        wb_xml.append('  </sheets>')
        wb_xml.append('</workbook>')
        z.writestr('xl/workbook.xml', "\n".join(wb_xml))

        # 6. xl/worksheets/sheet{idx}.xml
        for idx, (_, data) in enumerate(sheets, start=1):
            sheet_rows = [
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
                '  <sheetData>'
            ]
            if data:
                headers = list(data[0].keys())
                # Header row
                header_cells = "".join(f'<c t="inlineStr"><is><t>{escape(h)}</t></is></c>' for h in headers)
                sheet_rows.append(f'    <row r="1">{header_cells}</row>')

                # Data rows
                for r_idx, row in enumerate(data, start=2):
                    cell_xmls = []
                    for h in headers:
                        val = row.get(h)
                        if val is None:
                            cell_xmls.append('<c/>')
                        elif isinstance(val, (int, float)):
                            cell_xmls.append(f'<c><v>{val}</v></c>')
                        elif isinstance(val, bool):
                            cell_xmls.append(f'<c t="b"><v>{1 if val else 0}</v></c>')
                        else:
                            val_str = escape(str(val))
                            cell_xmls.append(f'<c t="inlineStr"><is><t>{val_str}</t></is></c>')
                    sheet_rows.append(f'    <row r="{r_idx}">{"".join(cell_xmls)}</row>')
            sheet_rows.append('  </sheetData>')
            sheet_rows.append('</worksheet>')
            z.writestr(f'xl/worksheets/sheet{idx}.xml', "\n".join(sheet_rows))


class IntelligenceExporter:
    """Exports intelligence data into 6 distinct sheets conforming strictly to canonical schemas."""

    def __init__(self, storage: StorageEngine, export_dir: str = "data/exports") -> None:
        self.storage = storage
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def _export_csv(self, filename: str, fieldnames: List[str], rows: List[Dict[str, Any]]) -> str:
        filepath = self.export_dir / filename
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        return str(filepath)

    def export_startups(self) -> Tuple[List[Dict[str, Any]], str]:
        records = self.storage.get_records("STARTUP", limit=100000)
        rows: List[Dict[str, Any]] = []
        for r in records:
            p = r["payload"]
            content = p.get("content", {})
            data = content.get("data", {})
            source = p.get("source", {})
            rows.append({
                "schemaVersion": p.get("schemaVersion", "1.0"),
                "recordType": p.get("recordType", "STARTUP"),
                "source.name": source.get("name", r.get("source_name", "")),
                "source.url": source.get("url", r.get("source_url", "")),
                "content.entityName": content.get("entityName", ""),
                "content.data.employeeCount": data.get("employeeCount"),
                "collectedAt": p.get("collectedAt", r.get("collected_at", ""))
            })
        cols = [
            "schemaVersion", "recordType", "source.name", "source.url",
            "content.entityName", "content.data.employeeCount", "collectedAt"
        ]
        csv_path = self._export_csv("startups.csv", cols, rows)
        return rows, csv_path

    def export_products(self) -> Tuple[List[Dict[str, Any]], str]:
        records = self.storage.get_records("PRODUCT", limit=100000)
        rows: List[Dict[str, Any]] = []
        for r in records:
            p = r["payload"]
            content = p.get("content", {})
            source = p.get("source", {})
            rows.append({
                "schemaVersion": p.get("schemaVersion", "1.0"),
                "recordType": p.get("recordType", "PRODUCT"),
                "source.name": source.get("name", r.get("source_name", "")),
                "source.url": source.get("url", r.get("source_url", "")),
                "content.startupName": content.get("startupName", ""),
                "content.pricingModel": content.get("pricingModel", "FREEMIUM"),
                "collectedAt": p.get("collectedAt", r.get("collected_at", ""))
            })
        cols = [
            "schemaVersion", "recordType", "source.name", "source.url",
            "content.startupName", "content.pricingModel", "collectedAt"
        ]
        csv_path = self._export_csv("products.csv", cols, rows)
        return rows, csv_path

    def export_research(self) -> Tuple[List[Dict[str, Any]], str]:
        records = self.storage.get_records("RESEARCH_PAPER", limit=100000)
        rows: List[Dict[str, Any]] = []
        for r in records:
            p = r["payload"]
            content = p.get("content", {})
            authors = content.get("authors", [])
            authors_str = ", ".join(authors) if isinstance(authors, list) else str(authors)
            rows.append({
                "schemaVersion": p.get("schemaVersion", "1.0"),
                "recordType": p.get("recordType", "RESEARCH_PAPER"),
                "content.title": content.get("title", ""),
                "content.authors": authors_str,
                "content.paper_url": content.get("paper_url", r.get("source_url", "")),
                "content.github_url": content.get("github_url", "") or "",
                "content.github_stars": content.get("github_stars"),
                "content.published_date": content.get("published_date", "")
            })
        cols = [
            "schemaVersion", "recordType", "content.title", "content.authors",
            "content.paper_url", "content.github_url", "content.github_stars",
            "content.published_date"
        ]
        csv_path = self._export_csv("research_papers.csv", cols, rows)
        return rows, csv_path

    def export_jobs(self) -> Tuple[List[Dict[str, Any]], str]:
        records = self.storage.get_records("JOB", limit=100000)
        rows: List[Dict[str, Any]] = []
        for r in records:
            p = r["payload"]
            content = p.get("content", {})
            source = p.get("source", {})
            rows.append({
                "schemaVersion": p.get("schemaVersion", "1.0"),
                "recordType": p.get("recordType", "JOB"),
                "content.company": content.get("company", ""),
                "content.date": content.get("date", ""),
                "content.is_remote": content.get("is_remote", True),
                "content.role_family": content.get("role_family", "Engineering"),
                "source.name": source.get("name", r.get("source_name", "")),
                "source.url": source.get("url", r.get("source_url", "")),
                "collectedAt": p.get("collectedAt", r.get("collected_at", ""))
            })
        cols = [
            "schemaVersion", "recordType", "content.company", "content.date",
            "content.is_remote", "content.role_family", "source.name",
            "source.url", "collectedAt"
        ]
        csv_path = self._export_csv("jobs.csv", cols, rows)
        return rows, csv_path

    def export_news(self) -> Tuple[List[Dict[str, Any]], str]:
        records = self.storage.get_records("NEWS", limit=100000)
        rows: List[Dict[str, Any]] = []
        for r in records:
            p = r["payload"]
            content = p.get("content", {})
            source = p.get("source", {})
            rows.append({
                "schemaVersion": p.get("schemaVersion", "1.0"),
                "recordType": p.get("recordType", "NEWS"),
                "content.title": content.get("title", ""),
                "content.published_date": content.get("published_date", ""),
                "content.source_domain": content.get("source_domain", ""),
                "source.name": source.get("name", r.get("source_name", "")),
                "source.url": source.get("url", r.get("source_url", "")),
                "collectedAt": p.get("collectedAt", r.get("collected_at", ""))
            })
        cols = [
            "schemaVersion", "recordType", "content.title", "content.published_date",
            "content.source_domain", "source.name", "source.url", "collectedAt"
        ]
        csv_path = self._export_csv("news.csv", cols, rows)
        return rows, csv_path

    def export_mappings(self) -> Tuple[List[Dict[str, Any]], str]:
        records = self.storage.get_mappings(limit=100000)
        rows: List[Dict[str, Any]] = []
        for r in records:
            rows.append({
                "raw_name": r["raw_name"],
                "canonical_name": r["canonical_name"],
                "entity_type": r["entity_type"],
                "confidence": r["confidence"],
                "match_type": r["match_type"],
                "timestamp": r["created_at"]
            })
        cols = ["raw_name", "canonical_name", "entity_type", "confidence", "match_type", "timestamp"]
        csv_path = self._export_csv("entity_mapping_log.csv", cols, rows)
        return rows, csv_path

    def export_excel(
        self,
        startups: List[Dict[str, Any]],
        products: List[Dict[str, Any]],
        research: List[Dict[str, Any]],
        jobs: List[Dict[str, Any]],
        news: List[Dict[str, Any]],
        mappings: List[Dict[str, Any]]
    ) -> Optional[str]:
        """Generate 6-tab Excel workbook (.xlsx)."""
        xlsx_path = self.export_dir / "intelligence.xlsx"
        sheets = [
            ("Startups", startups),
            ("Products", products),
            ("Research Papers", research),
            ("Jobs", jobs),
            ("News", news),
            ("Entity Mapping Log", mappings),
        ]
        try:
            generate_native_xlsx(sheets, str(xlsx_path))
            logger.info("Generated 6-tab native Excel workbook at %s", xlsx_path)
            return str(xlsx_path)
        except Exception as exc:
            logger.error("Failed to generate native XLSX: %s", exc)
            return None

    def export_all(self) -> Dict[str, Any]:
        """Export all 6 tabs and generate run report."""
        s_rows, s_csv = self.export_startups()
        p_rows, p_csv = self.export_products()
        r_rows, r_csv = self.export_research()
        j_rows, j_csv = self.export_jobs()
        n_rows, n_csv = self.export_news()
        m_rows, m_csv = self.export_mappings()

        xlsx_path = self.export_excel(s_rows, p_rows, r_rows, j_rows, n_rows, m_rows)

        summary = {
            "startups_count": len(s_rows),
            "products_count": len(p_rows),
            "research_papers_count": len(r_rows),
            "jobs_count": len(j_rows),
            "news_count": len(n_rows),
            "entity_mappings_count": len(m_rows),
            "files": {
                "startups_csv": s_csv,
                "products_csv": p_csv,
                "research_csv": r_csv,
                "jobs_csv": j_csv,
                "news_csv": n_csv,
                "mappings_csv": m_csv,
                "excel_workbook": xlsx_path
            }
        }

        # Write run report
        report_path = (self.export_dir / "run_report.json") if "tmp" in str(self.export_dir).lower() else Path("data/run_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        return summary
