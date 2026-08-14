from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Iterator


REQUIRED_SECTIONS = (
    "identity",
    "education",
    "employment",
    "projects",
    "skills",
    "evidence",
    "unresolved",
)
ARRAY_SECTIONS = REQUIRED_SECTIONS[1:]
EVIDENCE_STATUSES = {"verified", "partial", "conflict", "missing"}
RESUME_ARRAY_SECTIONS = ("education", "experience", "projects", "skills")
TEMPLATE_MARKERS = (
    "__DOCUMENT_TITLE__",
    "<!--TARGET_PANEL-->",
    "<!--RESUME_CONTENT-->",
    "__STORAGE_KEY_JSON__",
    "__UNRESOLVED_COUNT__",
)
DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "resume-editor-template.html"
)
CONTACT_UNRESOLVED_ITEMS = (
    ("phone", "candidate-phone", "请补充电话"),
    ("email", "candidate-email", "请补充邮箱"),
)
CONTACT_UNRESOLVED_IDS = frozenset(item_id for _, item_id, _ in CONTACT_UNRESOLVED_ITEMS)
WINDOWS_RESERVED_DEVICE_NAME = re.compile(
    r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", re.IGNORECASE
)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def validate_candidate_profile(profile: dict) -> None:
    schema_version = profile.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
    ):
        raise ValueError("schema_version must be 1")

    for section in REQUIRED_SECTIONS:
        if section not in profile:
            raise ValueError(f"missing required section: {section}")

    if not isinstance(profile["identity"], dict):
        raise ValueError("identity must be an object")

    for section in ARRAY_SECTIONS:
        if not isinstance(profile[section], list):
            raise ValueError(f"{section} must be an array")

    evidence_ids: set[str] = set()
    for evidence in profile["evidence"]:
        if not isinstance(evidence, dict):
            raise ValueError("evidence item must be an object")

        evidence_id = evidence.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError("evidence_id must be nonempty")
        if evidence_id in evidence_ids:
            raise ValueError("evidence_id must be unique")
        evidence_ids.add(evidence_id)

        status = evidence.get("status")
        if not isinstance(status, str) or status not in EVIDENCE_STATUSES:
            raise ValueError("unsupported evidence status")

        sources = evidence.get("sources")
        if not isinstance(sources, list):
            raise ValueError("evidence sources must be an array")
        if not sources:
            raise ValueError("evidence sources must be nonempty")
        for source in sources:
            _validate_evidence_source(source)


def _validate_evidence_source(source: object) -> None:
    if not isinstance(source, dict):
        raise ValueError("evidence source must be an object")
    if not isinstance(source.get("file"), str) or not source["file"].strip():
        raise ValueError("source file must be nonempty")
    if not isinstance(source.get("location"), str) or not source["location"].strip():
        raise ValueError("source location must be nonempty")


def validate_resume_data(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("resume root must be an object")

    schema_version = data.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
    ):
        raise ValueError("schema_version must be 1")

    for section in ("target", "candidate", *RESUME_ARRAY_SECTIONS):
        if section not in data:
            raise ValueError(f"missing required section: {section}")

    target = data["target"]
    candidate = data["candidate"]
    if not isinstance(target, dict):
        raise ValueError("target must be an object")
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be an object")
    for field in ("company", "role", "date"):
        _require_nonblank_string(target, field, f"target {field}")
    _require_nonblank_string(candidate, "name", "candidate name")

    _validate_optional_string_fields(target, ("match_summary",))
    _validate_optional_string_fields(candidate, ("phone", "email", "location", "summary"))
    _validate_optional_string_array(target, "keywords", "target keywords")
    _validate_optional_string_array(target, "changes", "target changes")

    for section in RESUME_ARRAY_SECTIONS:
        if not isinstance(data[section], list):
            raise ValueError(f"{section} must be an array")

    block_ids: set[str] = set()
    for education in data["education"]:
        _validate_editable_record(education, "education item", block_ids)
        _validate_optional_string_fields(
            education,
            ("institution", "degree", "field", "dates", "details"),
        )

    for experience in data["experience"]:
        if not isinstance(experience, dict):
            raise ValueError("experience item must be an object")
        _validate_optional_string_fields(
            experience,
            ("employer", "role", "dates", "location"),
        )
        groups = experience.get("groups")
        if not isinstance(groups, list):
            raise ValueError("experience groups must be an array")
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError("experience group must be an object")
            _require_nonblank_string(group, "title", "experience group title")
            bullets = group.get("bullets")
            if not isinstance(bullets, list):
                raise ValueError("experience bullets must be an array")
            for bullet in bullets:
                _validate_editable_record(bullet, "experience bullet", block_ids)
                _validate_optional_string_fields(bullet, ("text",))
                _validate_optional_string_array(
                    bullet, "evidence_ids", "experience evidence_ids"
                )

    for project in data["projects"]:
        _validate_editable_record(project, "project item", block_ids)
        _validate_optional_string_fields(
            project,
            ("name", "role", "dates", "summary"),
        )
        _validate_optional_string_array(project, "bullets", "project bullets")

    for skill in data["skills"]:
        _validate_editable_record(skill, "skill item", block_ids)
        _validate_optional_string_fields(skill, ("category",))
        _validate_optional_string_array(skill, "items", "skill items")


def _require_nonblank_string(record: dict, field: str, label: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonblank")
    return value


def _validate_optional_string_fields(record: dict, fields: tuple[str, ...]) -> None:
    for field in fields:
        if field in record and not isinstance(record[field], str):
            raise ValueError(f"{field} must be a string")


def _validate_optional_string_array(record: dict, field: str, label: str) -> None:
    if field not in record:
        return
    value = record[field]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be an array of strings")


def _validate_editable_record(
    record: object, label: str, block_ids: set[str]
) -> None:
    if not isinstance(record, dict):
        raise ValueError(f"{label} must be an object")
    block_id = record.get("block_id")
    if not isinstance(block_id, str) or not block_id.strip():
        raise ValueError("editable block_id must be nonblank")
    if block_id in CONTACT_UNRESOLVED_IDS:
        raise ValueError("editable block_id is reserved for contact gaps")
    if block_id in block_ids:
        raise ValueError("editable block_id must be unique")
    block_ids.add(block_id)
    prompt = record.get("review_prompt")
    if prompt is not None and not isinstance(prompt, str):
        raise ValueError("review_prompt must be a string or null")


def windows_slug(value: str) -> str:
    collapsed = re.sub(r"[\s<>:\"/\\|?*'“”‘’_-]+", "-", value.strip())
    slug = collapsed.rstrip(" .-").lstrip(" .-")
    if not slug:
        raise ValueError("windows slug must not be empty")
    if WINDOWS_RESERVED_DEVICE_NAME.fullmatch(slug):
        raise ValueError("windows slug must not use a reserved Windows device name")
    return slug


def iter_review_items(value: object) -> Iterator[tuple[str, str]]:
    seen: set[str] = set()

    def walk(current: object) -> Iterator[tuple[str, str]]:
        if isinstance(current, dict):
            block_id = current.get("block_id")
            prompt = current.get("review_prompt")
            if (
                isinstance(block_id, str)
                and block_id.strip()
                and isinstance(prompt, str)
                and prompt.strip()
                and block_id not in seen
            ):
                seen.add(block_id)
                yield block_id, prompt
            for child in current.values():
                yield from walk(child)
        elif isinstance(current, list):
            for child in current:
                yield from walk(child)

    yield from walk(value)


def count_review_items(data: dict) -> int:
    return sum(1 for _ in iter_review_items(data))


def _iter_missing_contact_items(candidate: object) -> Iterator[tuple[str, str, str]]:
    if not isinstance(candidate, dict):
        return
    for field, item_id, prompt in CONTACT_UNRESOLVED_ITEMS:
        value = candidate.get(field, "")
        if not isinstance(value, str) or not value.strip():
            yield field, item_id, prompt


def iter_unresolved_items(data: dict) -> Iterator[tuple[str, str]]:
    seen: set[str] = set()
    for _, item_id, prompt in _iter_missing_contact_items(data.get("candidate")):
        seen.add(item_id)
        yield item_id, prompt
    for item_id, prompt in iter_review_items(data):
        if item_id not in seen:
            seen.add(item_id)
            yield item_id, prompt


def count_unresolved_items(data: dict) -> int:
    return sum(1 for _ in iter_unresolved_items(data))


def render_review_markup(block_id: str, prompt: str | None) -> str:
    if not isinstance(prompt, str) or not prompt.strip():
        return ""
    safe_id = _escape(block_id)
    safe_prompt = _escape(prompt)
    return (
        f'<span class="review-badge screen-only" data-review-item="{safe_id}" '
        'contenteditable="false">待核实</span>'
        f'<aside class="review-note screen-only" data-review-item="{safe_id}" '
        f'contenteditable="false">{safe_prompt}</aside>'
    )


def render_editable_block(
    tag: str, block_id: str, body_html: str, prompt: str | None
) -> str:
    if tag not in {"div", "li"}:
        raise ValueError("editable block tag must be div or li")
    safe_id = _escape(block_id)
    return (
        f'<{tag} class="editable-block" data-block-id="{safe_id}">'
        '<button class="block-drag-handle" contenteditable="false" type="button" '
        'aria-label="移动此内容块">⋮</button>'
        f'<div class="block-content">{body_html}</div>'
        f'{render_review_markup(block_id, prompt)}'
        '<button class="block-resize-handle" contenteditable="false" type="button" '
        'aria-label="调整此内容块高度"></button>'
        f'</{tag}>'
    )


def render_target_panel(data: dict) -> str:
    return _render_target_panel(data, list(iter_unresolved_items(data)))


def _render_target_panel(
    data: dict, unresolved_items: list[tuple[str, str]]
) -> str:
    target = data["target"]
    keywords = "".join(
        f'<span class="keyword">{_escape(keyword)}</span>'
        for keyword in target.get("keywords", [])
    )
    changes = "".join(
        f"<li>{_escape(change)}</li>" for change in target.get("changes", [])
    )
    prompts = "".join(
        f'<li data-review-item="{_escape(block_id)}">{_escape(prompt)}</li>'
        for block_id, prompt in unresolved_items
    )
    if not prompts:
        prompts = '<li class="empty-review">无待核实项</li>'
    return (
        '<p class="eyebrow">目标岗位</p>'
        f'<h1>{_escape(target["role"])}</h1>'
        f'<p class="job-company">{_escape(target["company"])} · '
        f'{_escape(target["date"])}</p>'
        '<section class="panel-section"><h2>关键词</h2>'
        f'<div class="keyword-list">{keywords}</div></section>'
        '<section class="panel-section"><h2>匹配摘要</h2>'
        f'<p>{_escape(target.get("match_summary", ""))}</p></section>'
        '<section class="panel-section"><h2>本次调整</h2>'
        f'<ul class="panel-list">{changes}</ul></section>'
        '<section class="panel-section"><h2>待核实 '
        f'<span class="review-count">{len(unresolved_items)}</span></h2>'
        f'<ul class="panel-list review-list">{prompts}</ul></section>'
        '<p class="privacy-note">内容与照片仅保存在当前浏览器。</p>'
    )


def render_header(candidate: dict) -> str:
    contacts = []
    for field in ("phone", "email", "location"):
        value = candidate.get(field, "")
        if isinstance(value, str) and value.strip():
            contacts.append(
                f'<span data-contact="{field}">{_escape(value)}</span>'
            )
    missing_prompts = [
        '<span class="missing-info screen-only" '
        f'data-review-item="{_escape(item_id)}" '
        f'data-missing-info="{_escape(field)}" contenteditable="false">'
        f'{_escape(prompt)}</span>'
        for field, item_id, prompt in _iter_missing_contact_items(candidate)
    ]
    summary = candidate.get("summary", "")
    summary_markup = (
        f'<p class="candidate-summary">{_escape(summary)}</p>' if summary else ""
    )
    return (
        '<header class="resume-header">'
        '<div class="identity">'
        f'<h1 class="resume-name">{_escape(candidate["name"])}</h1>'
        f'<div class="contact-row">{"<span class=\"contact-separator\">｜</span>".join(contacts)}</div>'
        f'<div class="missing-info-row">{"".join(missing_prompts)}</div>'
        f'{summary_markup}</div>'
        '<div class="photo-uploader" data-photo-uploader contenteditable="false">'
        '<button class="photo-upload-trigger" type="button" aria-label="上传本地照片">'
        '<img class="photo-image" alt="简历照片" hidden>'
        '<span class="photo-empty-state">上传照片<small>仅本地保存</small></span>'
        '</button><div class="photo-controls" hidden>'
        '<button type="button" data-photo-action="replace">更换</button>'
        '<button type="button" data-photo-action="remove">删除</button>'
        '</div></div></header>'
    )


def render_education(items: list[dict]) -> str:
    blocks = []
    for item in items:
        qualification = _join_nonblank((item.get("degree"), item.get("field")), " · ")
        body = (
            '<div class="resume-meta-row">'
            f'<strong>{_escape(item.get("institution", ""))}</strong>'
            f'<span>{_escape(item.get("dates", ""))}</span></div>'
        )
        if qualification:
            body += f'<p class="resume-subline">{qualification}</p>'
        if item.get("details"):
            body += f'<p class="resume-detail">{_escape(item["details"])}</p>'
        blocks.append(
            render_editable_block(
                "div", item["block_id"], body, item.get("review_prompt")
            )
        )
    return _render_section(
        "教育背景",
        f'<div class="education-list" data-sortable-group="education">{"".join(blocks)}</div>',
    )


def render_experience(items: list[dict]) -> str:
    entries = []
    for experience_index, item in enumerate(items):
        employer_line = _join_nonblank(
            (item.get("employer"), item.get("role")), " · "
        )
        place_line = _join_nonblank(
            (item.get("dates"), item.get("location")), " · "
        )
        groups = []
        for group_index, group in enumerate(item["groups"]):
            bullets = "".join(
                render_editable_block(
                    "li",
                    bullet["block_id"],
                    _escape(bullet.get("text", "")),
                    bullet.get("review_prompt"),
                )
                for bullet in group["bullets"]
            )
            groups.append(
                '<div class="experience-group">'
                '<h3 class="experience-group-title" contenteditable="false">'
                f'{_escape(group["title"])}</h3>'
                '<ul class="resume-list" '
                f'data-sortable-group="experience-{experience_index}-{group_index}">'
                f'{bullets}</ul></div>'
            )
        entries.append(
            '<article class="experience-entry">'
            '<div class="experience-meta" contenteditable="false">'
            f'<strong>{employer_line}</strong><span>{place_line}</span></div>'
            f'{"".join(groups)}</article>'
        )
    return _render_section("工作经历", "".join(entries))


def render_projects(items: list[dict]) -> str:
    blocks = []
    for item in items:
        heading = _join_nonblank((item.get("name"), item.get("role")), " · ")
        body = (
            '<div class="resume-meta-row">'
            f'<strong>{heading}</strong><span>{_escape(item.get("dates", ""))}</span>'
            '</div>'
        )
        if item.get("summary"):
            body += f'<p class="resume-detail">{_escape(item["summary"])}</p>'
        if item.get("bullets"):
            body += '<ul class="compact-list">' + "".join(
                f"<li>{_escape(bullet)}</li>" for bullet in item["bullets"]
            ) + "</ul>"
        blocks.append(
            render_editable_block(
                "div", item["block_id"], body, item.get("review_prompt")
            )
        )
    return _render_section(
        "项目经历",
        f'<div class="project-list" data-sortable-group="projects">{"".join(blocks)}</div>',
    )


def render_skills(items: list[dict]) -> str:
    blocks = []
    for item in items:
        category = item.get("category", "")
        prefix = f"<strong>{_escape(category)}：</strong>" if category else ""
        body = prefix + "、".join(_escape(value) for value in item.get("items", []))
        blocks.append(
            render_editable_block(
                "li", item["block_id"], body, item.get("review_prompt")
            )
        )
    return _render_section(
        "专业技能",
        f'<ul class="resume-list skills-list" data-sortable-group="skills">{"".join(blocks)}</ul>',
    )


def _render_section(title: str, body_html: str) -> str:
    return (
        '<section class="resume-section">'
        f'<h2 class="section-title" contenteditable="false">{title}</h2>'
        f'{body_html}</section>'
    )


def _join_nonblank(values: tuple[object, ...], separator: str) -> str:
    return separator.join(_escape(value) for value in values if str(value or "").strip())


def _escape(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def render_resume(data: dict, template: str) -> str:
    validate_resume_data(data)
    for marker in TEMPLATE_MARKERS:
        if marker not in template:
            raise ValueError(f"missing template marker: {marker}")

    target = data["target"]
    title = f'{target["company"]}｜{target["role"]}｜岗位定制简历'
    storage_key = (
        f'resume-editor:{windows_slug(target["company"])}:'
        f'{windows_slug(target["role"])}:v1'
    )
    unresolved_items = list(iter_unresolved_items(data))
    resume_content = "".join(
        (
            render_header(data["candidate"]),
            render_education(data["education"]),
            render_experience(data["experience"]),
            render_projects(data["projects"]),
            render_skills(data["skills"]),
        )
    )
    replacements = {
        "__DOCUMENT_TITLE__": _escape(title),
        "<!--TARGET_PANEL-->": _render_target_panel(data, unresolved_items),
        "<!--RESUME_CONTENT-->": resume_content,
        "__STORAGE_KEY_JSON__": json.dumps(storage_key, ensure_ascii=False),
        "__UNRESOLVED_COUNT__": str(len(unresolved_items)),
    }
    rendered = template
    for marker, replacement in replacements.items():
        rendered = rendered.replace(marker, replacement)
    return rendered


def build_file(input_path: Path, output_path: Path, template_path: Path) -> None:
    data = load_json(input_path)
    template = template_path.read_text(encoding="utf-8")
    rendered = render_resume(data, template)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a standalone resume editor")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE_PATH)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    build_file(args.input, args.output, args.template)


if __name__ == "__main__":
    main()
