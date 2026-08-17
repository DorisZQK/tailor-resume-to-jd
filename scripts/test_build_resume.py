from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import build_resume
from build_resume import load_json, validate_candidate_profile


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEXT_CODE_SUFFIXES = {".html", ".json", ".md", ".mjs", ".py", ".yaml"}


class CandidateProfileTests(unittest.TestCase):
    def test_accepts_schema_version_one_profile(self) -> None:
        validate_candidate_profile(self._valid_profile())

    def test_rejects_unsupported_schema_version(self) -> None:
        profile = self._valid_profile()
        profile["schema_version"] = 0

        with self.assertRaisesRegex(ValueError, "schema_version must be 1"):
            validate_candidate_profile(profile)

    def test_rejects_noninteger_schema_version(self) -> None:
        profile = self._valid_profile()
        profile["schema_version"] = 1.0

        with self.assertRaisesRegex(ValueError, "schema_version must be 1"):
            validate_candidate_profile(profile)

    def test_rejects_unsupported_evidence_status(self) -> None:
        profile = self._valid_profile()
        profile["evidence"][0]["status"] = "assumed"

        with self.assertRaisesRegex(ValueError, "unsupported evidence status"):
            validate_candidate_profile(profile)

    def test_rejects_verified_evidence_without_sources(self) -> None:
        profile = self._valid_profile()
        profile["evidence"][0]["sources"] = []

        with self.assertRaisesRegex(ValueError, "evidence sources must be nonempty"):
            validate_candidate_profile(profile)

    def test_rejects_missing_evidence_without_sources(self) -> None:
        profile = self._valid_profile()
        profile["evidence"][0]["status"] = "missing"
        profile["evidence"][0]["sources"] = []

        with self.assertRaisesRegex(ValueError, "evidence sources must be nonempty"):
            validate_candidate_profile(profile)

    def test_rejects_nonstring_evidence_status(self) -> None:
        profile = self._valid_profile()
        profile["evidence"][0]["status"] = ["verified"]

        with self.assertRaisesRegex(ValueError, "unsupported evidence status"):
            validate_candidate_profile(profile)

    def test_accepts_all_supported_statuses_with_nonempty_sources(self) -> None:
        for status in ("verified", "partial", "conflict", "missing"):
            with self.subTest(status=status):
                profile = self._valid_profile()
                profile["evidence"][0]["status"] = status
                validate_candidate_profile(profile)

    def test_load_json_rejects_array_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            profile_path = Path(temporary_directory) / "profile.json"
            profile_path.write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "JSON root must be an object"):
                load_json(profile_path)

    def test_rejects_duplicate_evidence_ids(self) -> None:
        profile = self._valid_profile()
        profile["evidence"].append(
            {
                "evidence_id": "project-001",
                "status": "partial",
                "sources": [{"file": "source-b.txt", "location": "line 2"}],
            }
        )

        with self.assertRaisesRegex(ValueError, "evidence_id must be unique"):
            validate_candidate_profile(profile)

    def test_rejects_evidence_source_without_location(self) -> None:
        profile = self._valid_profile()
        profile["evidence"][0]["sources"] = [{"file": "source-a.txt"}]

        with self.assertRaisesRegex(ValueError, "source location must be nonempty"):
            validate_candidate_profile(profile)

    @staticmethod
    def _valid_profile() -> dict:
        return {
            "schema_version": 1,
            "identity": {"initials": "QX"},
            "education": [],
            "employment": [{"title": "Sample role"}],
            "projects": [{"name": "Sample project"}],
            "skills": ["Python"],
            "evidence": [
                {
                    "evidence_id": "project-001",
                    "status": "verified",
                    "sources": [{"file": "source-a.txt", "location": "line 1"}],
                }
            ],
            "unresolved": [],
        }


class ResumeRendererTests(unittest.TestCase):
    def test_escapes_user_content_and_never_adds_network_clients(self) -> None:
        data = self._valid_resume()
        injection = '<script src="https://bad.example/x.js"></script>'
        data["education"][0]["details"] = injection

        rendered = self._render(data)

        self.assertIn(
            "&lt;script src=&quot;https://bad.example/x.js&quot;&gt;&lt;/script&gt;",
            rendered,
        )
        self.assertNotIn(injection, rendered)
        self.assertNotRegex(rendered, r"<script\s+[^>]*\bsrc\s*=")
        self.assertNotRegex(rendered, r"<link\s+[^>]*\bhref\s*=")
        for forbidden_client in ("fetch(", "XMLHttpRequest", "WebSocket"):
            self.assertNotIn(forbidden_client, rendered)

    def test_renders_review_markup_and_print_hides_annotations(self) -> None:
        data = self._valid_resume()
        prompt = "请补充 <数量> & 来源。"
        data["experience"][0]["groups"][0]["bullets"][0][
            "review_prompt"
        ] = prompt

        rendered = self._render(data)

        self.assertIn('data-review-item="experience-analysis-001"', rendered)
        self.assertIn("请补充 &lt;数量&gt; &amp; 来源。", rendered)
        self.assertRegex(
            rendered,
            r"@media\s+print\s*\{[\s\S]*?\.review-note[\s\S]*?display:\s*none\s*!important",
        )
        self.assertIn('class="review-badge screen-only"', rendered)
        self.assertIn('contenteditable="false"', rendered)

    def test_renders_fixed_a4_page_and_exact_job_storage_key(self) -> None:
        rendered = self._render(self._valid_resume())

        self.assertRegex(
            rendered,
            r"\.resume-page\s*\{[^}]*width:\s*210mm;[^}]*height:\s*297mm;",
        )
        self.assertIn("@page { size: A4; margin: 0; }", rendered)
        self.assertIn(
            'const STORAGE_KEY = "resume-editor:星河零售:商业数据分析师:v1";',
            rendered,
        )
        self.assertNotIn("min-height: 297mm", rendered)

    def test_windows_slug_removes_reserved_characters_and_collapses_separators(self) -> None:
        self.assertEqual(
            "星河-零售-A",
            build_resume.windows_slug('星河/零售:*? "A"'),
        )

    def test_windows_slug_rejects_empty_and_reserved_device_names(self) -> None:
        for value in ('<>:"/\\|?*', " . "):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "windows slug must not be empty"):
                    build_resume.windows_slug(value)

        for value in ("CON", "con", "PRN", "AUX", "NUL.txt", "COM1", "com9.log", "LPT1", "lpt9.resume"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "reserved Windows device name"):
                    build_resume.windows_slug(value)

    def test_cli_writes_utf8_standalone_html_with_only_fictional_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            input_path = temporary_root / "resume.json"
            output_path = temporary_root / "resume.html"
            input_path.write_text(
                json.dumps(self._valid_resume(), ensure_ascii=False), encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_ROOT / "scripts" / "build_resume.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)
            output_bytes = output_path.read_bytes()
            rendered = output_bytes.decode("utf-8")
            self.assertIn("林若安", rendered)
            self.assertIn("星河零售", rendered)
            self.assertIn("云帆研究社", rendered)
            self.assertIn("林若安".encode("utf-8"), output_bytes)
            self.assertNotIn("\ufeff", rendered)
            self.assertNotIn("郭" + "晶" + "珏", rendered)
            self.assertNotIn("World" + "panel", rendered)

    def test_validate_resume_data_rejects_required_field_and_type_errors(self) -> None:
        cases = []

        value = self._valid_resume()
        value["schema_version"] = True
        cases.append((value, "schema_version must be 1"))

        value = self._valid_resume()
        del value["target"]
        cases.append((value, "missing required section: target"))

        value = self._valid_resume()
        value["target"]["role"] = "   "
        cases.append((value, "target role must be nonblank"))

        value = self._valid_resume()
        value["candidate"]["name"] = ""
        cases.append((value, "candidate name must be nonblank"))

        value = self._valid_resume()
        value["education"] = {}
        cases.append((value, "education must be an array"))

        value = self._valid_resume()
        value["experience"][0]["groups"] = {}
        cases.append((value, "experience groups must be an array"))

        value = self._valid_resume()
        value["experience"][0]["groups"][0]["bullets"] = ["not an object"]
        cases.append((value, "experience bullet must be an object"))

        value = self._valid_resume()
        value["projects"][0]["block_id"] = ""
        cases.append((value, "editable block_id must be nonblank"))

        value = self._valid_resume()
        value["skills"][0]["block_id"] = value["education"][0]["block_id"]
        cases.append((value, "editable block_id must be unique"))

        value = self._valid_resume()
        value["skills"][0]["block_id"] = "candidate-phone"
        cases.append((value, "editable block_id is reserved for contact gaps"))

        for malformed, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    build_resume.validate_resume_data(malformed)

    def test_review_collector_recurses_and_deduplicates_by_block_id(self) -> None:
        data = {
            "first": {
                "block_id": "experience-analysis-001",
                "review_prompt": "first prompt",
            },
            "nested": [
                {
                    "block_id": "experience-analysis-001",
                    "review_prompt": "duplicate prompt",
                },
                {"block_id": "project-001", "review_prompt": "project prompt"},
                {"block_id": "ignored", "review_prompt": "  "},
            ],
        }

        items = list(build_resume.iter_review_items(data))

        self.assertEqual(
            [
                ("experience-analysis-001", "first prompt"),
                ("project-001", "project prompt"),
            ],
            items,
        )
        self.assertEqual(2, build_resume.count_review_items(data))

    def test_unresolved_collector_includes_missing_contacts_with_stable_ids(self) -> None:
        data = self._without_review_prompts()

        items = list(build_resume.iter_unresolved_items(data))
        rendered = self._render(data)

        self.assertEqual(
            [
                ("candidate-phone", "请补充电话"),
                ("candidate-email", "请补充邮箱"),
            ],
            items,
        )
        self.assertEqual(2, build_resume.count_unresolved_items(data))
        self.assertIn('data-unresolved-count="2"', rendered)
        self.assertIn(
            'class="missing-info screen-only" data-review-item="candidate-phone" '
            'data-missing-info="phone" contenteditable="false">请补充电话</span>',
            rendered,
        )
        self.assertIn(
            'class="missing-info screen-only" data-review-item="candidate-email" '
            'data-missing-info="email" contenteditable="false">请补充邮箱</span>',
            rendered,
        )

    def test_unresolved_count_tracks_one_or_zero_missing_contacts(self) -> None:
        one_missing = self._without_review_prompts()
        one_missing["candidate"]["phone"] = "138" + "0000" + "0000"

        self.assertEqual(1, build_resume.count_unresolved_items(one_missing))
        self.assertIn('data-unresolved-count="1"', self._render(one_missing))

        resolved = self._resolved_resume()
        self.assertEqual(0, build_resume.count_unresolved_items(resolved))
        self.assertIn('data-unresolved-count="0"', self._render(resolved))

    def test_unresolved_collector_deduplicates_duplicate_block_review_ids(self) -> None:
        data = {
            "candidate": dict(phone="present", email="present"),
            "reviews": [
                {"block_id": "review-001", "review_prompt": "first"},
                {"block_id": "review-001", "review_prompt": "duplicate"},
            ],
        }

        self.assertEqual(
            [("review-001", "first")],
            list(build_resume.iter_unresolved_items(data)),
        )
        self.assertEqual(1, build_resume.count_unresolved_items(data))

    def test_target_panel_prompt_count_matches_export_marker(self) -> None:
        rendered = self._render(self._without_review_prompts())
        marker = re.search(r'data-unresolved-count="(\d+)"', rendered)
        self.assertIsNotNone(marker)
        panel_list = rendered.split(
            '<ul class="panel-list review-list">', 1
        )[1].split("</ul>", 1)[0]
        panel_item_count = panel_list.count('<li data-review-item="')

        self.assertEqual(2, int(marker.group(1)))
        self.assertEqual(2, panel_item_count)
        self.assertEqual(int(marker.group(1)), panel_item_count)
        self.assertIn(
            f'<span class="review-count">{panel_item_count}</span>', rendered
        )

    def test_renders_required_sorting_boundaries_and_fixed_metadata(self) -> None:
        rendered = self._render(self._valid_resume())

        self.assertEqual(1, rendered.count('data-sortable-group="education"'))
        self.assertEqual(1, rendered.count('data-sortable-group="projects"'))
        self.assertEqual(1, rendered.count('data-sortable-group="skills"'))
        self.assertIn('data-sortable-group="experience-0-0"', rendered)
        self.assertIn('data-sortable-group="experience-0-1"', rendered)
        self.assertIn('data-block-id="experience-analysis-001"', rendered)
        self.assertIn('data-block-id="experience-quality-001"', rendered)
        self.assertIn('data-block-id="experience-reporting-001"', rendered)
        self.assertIn('data-block-id="skill-methods-001"', rendered)
        self.assertIn('class="experience-meta" contenteditable="false"', rendered)
        self.assertIn('class="experience-group-title" contenteditable="false"', rendered)
        self.assertIn('class="block-drag-handle" contenteditable="false"', rendered)
        self.assertIn('class="block-resize-handle" contenteditable="false"', rendered)
        self.assertIn("event.altKey", rendered)
        self.assertIn("dragState.group", rendered)

    def test_header_prompts_for_missing_contact_and_reserves_local_photo_area(self) -> None:
        rendered = self._render(self._valid_resume())

        self.assertIn('data-missing-info="phone"', rendered)
        self.assertIn('data-missing-info="email"', rendered)
        self.assertIn('data-photo-uploader', rendered)
        self.assertIn('canvas.width = PHOTO_WIDTH', rendered)
        self.assertIn('canvas.height = PHOTO_HEIGHT', rendered)
        self.assertIn("canvas.toDataURL('image/jpeg'", rendered)
        self.assertNotRegex(rendered, r'<img[^>]+src="')

    def test_photo_image_can_shrink_inside_the_reserved_grid_area(self) -> None:
        rendered = self._render(self._valid_resume())

        self.assertRegex(
            rendered,
            r"\.photo-image\s*\{[^}]*display:\s*block;[^}]*"
            r"min-width:\s*0;[^}]*min-height:\s*0;",
        )

    def test_print_styles_hide_carets_for_all_resume_content(self) -> None:
        rendered = self._render(self._valid_resume())
        print_css = rendered.split("@media print", 1)[1].split("</style>", 1)[0]

        self.assertRegex(
            print_css,
            r"\[data-resume-editor\]\s*,\s*"
            r"\[data-resume-editor\]\s+\*\s*\{[^}]*"
            r"caret-color:\s*transparent\s*!important;",
        )

    def test_export_contract_gates_only_unresolved_resumes(self) -> None:
        contact_only = self._render(self._without_review_prompts())
        unresolved = self._render(self._valid_resume())
        resolved = self._render(self._resolved_resume())

        self.assertIn('data-unresolved-count="2"', contact_only)
        self.assertIn('data-unresolved-count="3"', unresolved)
        self.assertIn('data-unresolved-count="0"', resolved)
        self.assertIn("unresolvedCount > 0", contact_only)
        self.assertIn("window.confirm", contact_only)
        self.assertIn("window.print()", contact_only)
        self.assertIn("待核实内容", contact_only)
        self.assertIn("是否继续导出", contact_only)

    def test_resolved_fixture_has_contacts_and_no_optional_review_markup(self) -> None:
        rendered = self._render(self._resolved_resume())

        self.assertIn("138" + "0000" + "0000", rendered)
        self.assertIn("resolved" + "@" + "example.invalid", rendered)
        for optional_markup in (
            'class="review-badge"',
            'class="review-note"',
            'data-missing-info="phone"',
            'data-missing-info="email"',
        ):
            with self.subTest(optional_markup=optional_markup):
                self.assertNotIn(optional_markup, rendered)

    def test_rejects_missing_template_markers_and_invalid_editable_tags(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing template marker"):
            build_resume.render_resume(self._valid_resume(), "<html></html>")
        with self.assertRaisesRegex(ValueError, "editable block tag must be div or li"):
            build_resume.render_editable_block("span", "block-001", "safe", None)

    @staticmethod
    def _valid_resume() -> dict:
        return {
            "schema_version": 1,
            "target": {
                "company": "星河零售",
                "role": "商业数据分析师",
                "date": "2026-08-14",
                "keywords": ["Python", "SQL", "商业分析", "客户沟通"],
                "match_summary": "分析工具与业务沟通能力匹配岗位要求。",
                "changes": ["突出零售分析", "前置核心工具"],
            },
            "candidate": {
                "name": "林若安",
                "phone": "",
                "email": "",
                "location": "杭州",
                "summary": "关注业务问题的数据分析从业者。",
            },
            "education": [
                {
                    "block_id": "education-001",
                    "institution": "南川大学",
                    "degree": "理学学士",
                    "field": "统计学",
                    "dates": "2018.09–2022.06",
                    "details": "主修统计建模与数据可视化。",
                    "review_prompt": None,
                }
            ],
            "experience": [
                {
                    "employer": "云帆研究社",
                    "role": "数据分析顾问",
                    "dates": "2022.07–至今",
                    "location": "杭州",
                    "groups": [
                        {
                            "title": "业务分析",
                            "bullets": [
                                {
                                    "block_id": "experience-analysis-001",
                                    "text": "使用 Python 与 SQL 整理零售指标并形成业务建议。",
                                    "evidence_ids": ["employment-analysis-001"],
                                    "review_prompt": "请补充该分析支持的报告数量。",
                                },
                                {
                                    "block_id": "experience-communication-001",
                                    "text": "与客户沟通口径并跟进交付问题。",
                                    "evidence_ids": ["employment-communication-001"],
                                    "review_prompt": None,
                                },
                                {
                                    "block_id": "experience-quality-001",
                                    "text": "复核指标口径并记录质量检查结果。",
                                    "evidence_ids": ["employment-quality-001"],
                                    "review_prompt": None,
                                },
                            ],
                        },
                        {
                            "title": "报告协作",
                            "bullets": [
                                {
                                    "block_id": "experience-reporting-001",
                                    "text": "整理分析结论并制作业务报告。",
                                    "evidence_ids": ["employment-reporting-001"],
                                    "review_prompt": None,
                                },
                                {
                                    "block_id": "experience-followup-001",
                                    "text": "跟进反馈并维护问题清单。",
                                    "evidence_ids": ["employment-followup-001"],
                                    "review_prompt": None,
                                },
                            ],
                        },
                    ],
                }
            ],
            "projects": [
                {
                    "block_id": "project-001",
                    "name": "门店趋势观察",
                    "role": "分析负责人",
                    "dates": "2025",
                    "summary": "整理门店经营指标并输出趋势结论。",
                    "bullets": ["建立指标字典", "复核异常数据"],
                    "review_prompt": None,
                }
            ],
            "skills": [
                {
                    "block_id": "skill-tools-001",
                    "category": "工具",
                    "items": ["Python", "SQL", "Excel"],
                    "review_prompt": None,
                },
                {
                    "block_id": "skill-business-001",
                    "category": "业务",
                    "items": ["商业分析", "客户沟通"],
                    "review_prompt": None,
                },
                {
                    "block_id": "skill-methods-001",
                    "category": "方法",
                    "items": ["指标设计", "质量检查"],
                    "review_prompt": None,
                },
            ],
        }

    @classmethod
    def _without_review_prompts(cls) -> dict:
        data = copy.deepcopy(cls._valid_resume())

        def clear_review_prompts(value: object) -> None:
            if isinstance(value, dict):
                if "review_prompt" in value:
                    value["review_prompt"] = None
                for child in value.values():
                    clear_review_prompts(child)
            elif isinstance(value, list):
                for child in value:
                    clear_review_prompts(child)

        clear_review_prompts(data)
        return data

    @classmethod
    def _resolved_resume(cls) -> dict:
        data = cls._without_review_prompts()
        data["candidate"]["phone"] = "138" + "0000" + "0000"
        data["candidate"]["email"] = "resolved" + "@" + "example.invalid"
        return data

    def _render(self, data: dict) -> str:
        template = (SKILL_ROOT / "assets" / "resume-editor-template.html").read_text(
            encoding="utf-8"
        )
        return build_resume.render_resume(data, template)


class PackageContractTests(unittest.TestCase):
    def test_validator_handles_generic_groups_and_preserves_unmoved_blocks(self) -> None:
        validator_text = (SKILL_ROOT / "scripts" / "validate_resume.mjs").read_text(
            encoding="utf-8"
        )

        for required_token in (
            "selectSortableGroup",
            "swapAdjacent",
            ":scope > .editable-block",
        ):
            with self.subTest(required_token=required_token):
                self.assertIn(required_token, validator_text)
        self.assertNotIn('const experienceGroup = \'[data-sortable-group^="experience-"]\'', validator_text)
        self.assertNotIn('const skillsGroup = \'[data-sortable-group="skills"]\'', validator_text)

    def test_validator_blocks_network_and_checks_nested_clipping(self) -> None:
        validator_text = (SKILL_ROOT / "scripts" / "validate_resume.mjs").read_text(
            encoding="utf-8"
        )

        for required_token in (
            "context.route(",
            "networkAttempts",
            "overflowX",
            "overflowY",
            "scrollWidth",
            "clientWidth",
        ):
            with self.subTest(required_token=required_token):
                self.assertIn(required_token, validator_text)

    def test_validator_enforces_network_policy_at_browser_context_scope(self) -> None:
        validator_text = (SKILL_ROOT / "scripts" / "validate_resume.mjs").read_text(
            encoding="utf-8"
        )

        for required_token in (
            "browser.newContext(",
            "serviceWorkers: 'block'",
            "context.route('**/*'",
            "context.routeWebSocket(",
            "connectToServer()",
            "webSocket.close(",
            "context.on('page'",
            "context.newPage(",
        ):
            with self.subTest(required_token=required_token):
                self.assertIn(required_token, validator_text)
        self.assertNotIn("page.route('**/*'", validator_text)
        self.assertNotIn("browser.newPage(", validator_text)
        self.assertLess(
            validator_text.index("context.route('**/*'"),
            validator_text.index("context.newPage("),
        )
        self.assertLess(
            validator_text.index("context.routeWebSocket("),
            validator_text.index("context.newPage("),
        )

    def test_validator_strengthens_storage_resize_prompt_and_photo_checks(self) -> None:
        validator_text = (SKILL_ROOT / "scripts" / "validate_resume.mjs").read_text(
            encoding="utf-8"
        )

        for required_token in (
            "expectedStorageKey",
            'data-missing-info="phone"',
            'data-missing-info="email"',
            "naturalWidth",
            "naturalHeight",
            "baselineHeight",
        ):
            with self.subTest(required_token=required_token):
                self.assertIn(required_token, validator_text)

    def test_validator_prepares_caret_free_print_capture_for_both_pdfs(self) -> None:
        validator_text = (SKILL_ROOT / "scripts" / "validate_resume.mjs").read_text(
            encoding="utf-8"
        )

        for required_runtime_check in (
            "prepareForPdfCapture",
            "isContentEditable",
            "removeAllRanges",
            "caretColor",
        ):
            with self.subTest(required_runtime_check=required_runtime_check):
                self.assertIn(required_runtime_check, validator_text)
        self.assertEqual(2, validator_text.count("await prepareForPdfCapture(page"))
        self.assertLess(
            validator_text.index("await prepareForPdfCapture(page"),
            validator_text.index("path: emptyPdfPath"),
        )
        self.assertLess(
            validator_text.rindex("await prepareForPdfCapture(page"),
            validator_text.index("path: photoPdfPath"),
        )
        self.assertIn(
            "await prepareForPdfCapture(page, 'before empty-photo PDF');\n"
            "  await page.pdf({ ...pdfOptions, path: emptyPdfPath });",
            validator_text,
        )

    def test_validator_exercises_export_gate_and_allows_absent_optional_print_content(self) -> None:
        validator_text = (SKILL_ROOT / "scripts" / "validate_resume.mjs").read_text(
            encoding="utf-8"
        )

        for required_runtime_contract in (
            "exerciseExportConfirmation",
            "__qaPrintCalls",
            "dialog.dismiss()",
            "dialog.accept()",
            "required = true",
            "required: false",
        ):
            with self.subTest(required_runtime_contract=required_runtime_contract):
                self.assertIn(required_runtime_contract, validator_text)
        self.assertIn(
            "await prepareForPdfCapture(page, 'before fictional-photo PDF');\n"
            "  await page.pdf({ ...pdfOptions, path: photoPdfPath });",
            validator_text,
        )

    def test_validator_exposes_browser_interaction_and_pdf_contract(self) -> None:
        validator_text = (SKILL_ROOT / "scripts" / "validate_resume.mjs").read_text(
            encoding="utf-8"
        )

        for required_token in (
            "--browser-executable",
            "--pdfinfo",
            "scrollHeight",
            "clientHeight",
            "Alt+ArrowDown",
            "resume-empty-photo.pdf",
            "resume-test-photo.pdf",
        ):
            with self.subTest(required_token=required_token):
                self.assertIn(required_token, validator_text)

    def test_future_package_files_exist(self) -> None:
        for relative_path in (
            "references/candidate-profile-schema.md",
            "assets/resume-editor-template.html",
            "scripts/build_resume.py",
            "scripts/validate_resume.mjs",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertTrue((SKILL_ROOT / relative_path).is_file())

    def test_skill_frontmatter_is_exact_and_document_is_bounded(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        expected_frontmatter = (
            "---\n"
            "name: tailor-resume-to-jd\n"
            "description: Analyze a complete job description, map the role "
            "to source-backed candidate evidence, restructure experience with natural "
            "STAR logic, remove AI-sounding language, and generate a one-page editable "
            "A4 HTML resume plus a JD analysis report. Use when a user provides a "
            "company, role, and JD and asks to tailor, rewrite, optimize, or generate a "
            "resume without inventing experience.\n"
            "---\n\n"
        )

        self.assertTrue(skill_text.startswith(expected_frontmatter))
        self.assertLess(len(skill_text.splitlines()), 500)
        placeholder = "TO" + "DO"
        placeholder_alt = "T" + "BD"
        self.assertNotRegex(skill_text, rf"\b(?:{placeholder}|{placeholder_alt})\b")

    def test_skill_has_the_eight_exact_workflow_headings_in_order(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertEqual(
            [
                "## 1. Inputs and private profile",
                "## 2. Analyze the JD",
                "## 3. Map evidence",
                "## 4. Rewrite",
                "## 5. Annotate gaps",
                "## 6. Write outputs",
                "## 7. Validate",
                "## 8. Deliver",
            ],
            re.findall(r"^## .+$", skill_text, re.MULTILINE),
        )

    def test_skill_workflow_contract_contains_required_analysis_and_evidence_rules(
        self,
    ) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for required_phrase in (
            "execution, coordination, decision-making, and management",
            "five to ten",
            "business pain points",
            "Use the supplied JD and user-authorized candidate files as the default source set",
            "Only research public company or business information when the user explicitly asks for that separate work",
            "evidence_id",
            "STAR",
            "never invent",
            "screen-only",
            "exactly one A4 page",
            "JD分析与修改依据.md",
            "build_resume.py",
            "validate_resume.mjs",
        ):
            with self.subTest(required_phrase=required_phrase):
                self.assertIn(required_phrase, skill_text)

        for removed_phrase in (
            "Research culture",
            "Browse current public information automatically",
            "official company sources",
            "culture sources and inferences",
        ):
            with self.subTest(removed_phrase=removed_phrase):
                self.assertNotIn(removed_phrase, skill_text)

        for binding_clause in (
            "create or use a profile evidence record with `status: missing`",
            "a stable `evidence_id`",
            "truthful source `file` and `location` values that point to the review/gap record",
            "labels a documented gap, not evidence of candidate experience",
            "Exclude missing, partial, and conflict facts from printable claims unless they are resolved and verified",
        ):
            with self.subTest(binding_clause=binding_clause):
                self.assertIn(binding_clause, skill_text)

    def test_skill_requires_private_finally_cleanup_outside_both_destinations(
        self,
    ) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for binding_clause in (
            "outside both the Skill folder and the final output directory",
            "finally-style cleanup",
            "success, failure, interruption, and retry",
            "Do not deliver while cleanup is incomplete",
        ):
            with self.subTest(binding_clause=binding_clause):
                self.assertIn(binding_clause, skill_text)

    def test_skill_binds_absolute_builder_and_validator_paths_and_exact_outputs(
        self,
    ) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        absolute_html = (
            "<absolute-output-dir>\\<company>-<role>-简历.html"
        )

        self.assertIn(
            "--output " + absolute_html,
            skill_text,
        )
        self.assertIn("--html " + absolute_html, skill_text)
        self.assertIn("Pass that same absolute HTML path", skill_text)
        self.assertIn(
            "contain exactly `JD分析与修改依据.md` and "
            "`<company>-<role>-简历.html`, with no other files",
            skill_text,
        )

    def test_skill_makes_every_validator_prerequisite_and_result_blocking(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for binding_clause in (
            "Create an empty temporary validation directory before invoking the validator",
            "Missing Node, Edge, or `pdfinfo`",
            "a nonzero validator exit",
            "missing `resume-empty-photo.pdf` or `resume-test-photo.pdf` evidence",
            "any browser, network, layout, or validator error",
            "blocking failure",
            "Never deliver or claim success until the exact validator command is green for both photo states",
        ):
            with self.subTest(binding_clause=binding_clause):
                self.assertIn(binding_clause, skill_text)

    def test_skill_final_response_contract_is_exactly_two_links(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn(
            "Return exactly two links: one to `JD分析与修改依据.md` and one to "
            "`<company>-<role>-简历.html`",
            skill_text,
        )
        self.assertIn(
            "Do not link the output directory, temporary files, or validation PDFs",
            skill_text,
        )

    def test_agent_metadata_has_exact_interface_shape_and_values(self) -> None:
        agent_text = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        lines = agent_text.splitlines()
        self.assertEqual("interface:", lines[0])
        interface = {}
        for line in lines[1:]:
            match = re.fullmatch(r'  ([a-z_]+): ("(?:[^"\\]|\\.)*")', line)
            self.assertIsNotNone(match, line)
            key, encoded_value = match.groups()
            self.assertNotIn(key, interface)
            interface[key] = json.loads(encoded_value)

        self.assertEqual(
            {
                "display_name": "JD 定制简历",
                "short_description": "拆解岗位要求并生成证据约束的一页 A4 HTML 简历",
                "default_prompt": (
                    "使用 $tailor-resume-to-jd 根据公司、岗位和完整 JD "
                    "生成分析报告及一页 A4 可编辑简历。"
                ),
            },
            interface,
        )

    def test_shareable_files_contain_no_candidate_data(self) -> None:
        self._assert_no_candidate_data(SKILL_ROOT)

    def test_privacy_scan_rejects_candidate_profile_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            (temporary_root / "candidate.json").write_text(
                json.dumps(self._candidate_profile()), encoding="utf-8"
            )
            self.assertEqual(
                ["candidate.json: candidate profile JSON"],
                self._candidate_data_violations(temporary_root),
            )

    def test_profile_detector_rejects_embedded_json_fragment(self) -> None:
        text = f"const profile = {json.dumps(self._candidate_profile())};"
        self.assertTrue(self._is_candidate_profile_json(text))

    def test_profile_detector_rejects_identity_with_experience(self) -> None:
        profile = dict(name="Example", experience=[dict(role="Analyst")])
        self.assertTrue(self._is_candidate_profile_json(json.dumps(profile)))

    def test_profile_detector_allows_ordinary_text(self) -> None:
        text = "Resume tailoring instructions with no candidate profile."
        self.assertFalse(self._is_candidate_profile_json(text))

    def test_profile_detector_allows_ordinary_code_metadata(self) -> None:
        text = 'const settings = {"name": "Resume title"};'
        self.assertFalse(self._is_candidate_profile_json(text))

    def test_profile_detector_allows_ordinary_experience_metadata(self) -> None:
        text = 'const settings = {"name": "Resume title", "experience": "Section label"};'
        self.assertFalse(self._is_candidate_profile_json(text))

    @staticmethod
    def _candidate_profile() -> dict[str, str]:
        return dict(name="Example", phone="555-0100")

    def _assert_no_candidate_data(self, root: Path) -> None:
        self.assertFalse(self._candidate_data_violations(root))

    def _candidate_data_violations(self, root: Path) -> list[str]:
        candidate_name = "郑" + "晴" + "珂"
        employer = "World" + "panel"
        mobile_number = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
        email_address = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
        violations = []

        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in TEXT_CODE_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            relative_path = path.relative_to(root)
            if mobile_number.search(text):
                violations.append(f"{relative_path}: Chinese mobile number")
            if email_address.search(text):
                violations.append(f"{relative_path}: email address")
            if candidate_name in text:
                violations.append(f"{relative_path}: candidate name")
            if employer in text:
                violations.append(f"{relative_path}: employer")
            if self._is_candidate_profile_json(text):
                violations.append(f"{relative_path}: candidate profile JSON")
        return violations

    @staticmethod
    def _is_candidate_profile_json(text: str) -> bool:
        decoder = json.JSONDecoder()
        identity_keys = {"name", "email", "phone"}

        for match in re.finditer(r"\{", text):
            try:
                value, _ = decoder.raw_decode(text[match.start() :])
            except json.JSONDecodeError:
                continue
            if not isinstance(value, dict):
                continue
            identity_field_count = sum(
                key in value and isinstance(value[key], (int, float, str))
                for key in identity_keys
            )
            has_profile_structure = any(
                key in value
                and isinstance(value[key], list)
                and any(isinstance(item, dict) for item in value[key])
                for key in ("experience", "education", "employment_history", "work_history")
            )
            if identity_field_count >= 2 or (
                identity_field_count == 1 and has_profile_structure
            ):
                return True
        return False


if __name__ == "__main__":
    unittest.main()

