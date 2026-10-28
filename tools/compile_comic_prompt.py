#!/usr/bin/env python3
"""Compile a bounded comic page spec into an ImageGen prompt.

The frozen source map is an input contract, not something this compiler infers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


MAX_REFERENCES = 5
MAX_VISIBLE_TEXT = 90
MAX_ACTION = 220
MAX_PROMPT = 8000
_HASH_CACHE: dict[tuple[str, int, int], str] = {}
_RAW_SPEECH = re.compile(r"[「『][^」』]+[」』]")
_PARAGRAPH_ID = re.compile(r"(?P<prefix>.*?)(?P<num>\d+)$")
_STYLE_KEYS = (
    "art_style",
    "color_palette",
    "linework",
    "lighting",
    "rendering",
    "mood",
)


class CompileError(ValueError):
    """Input failed a deterministic prompt-safety validation."""


def visual_prompt_section(prompt: str) -> str | None:
    """Separate drawable content from the approved lettering list."""
    starts = ("Visual panels:", "【分格】")
    visual = None
    for marker in starts:
        if marker in prompt:
            visual = prompt.split(marker, 1)[1]
            break
    if visual is None:
        match = re.search(r"(?m)^第\s*\d+\s*格[｜：:]", prompt)
        if match:
            visual = prompt[match.start():]
    if visual is None:
        return None
    ends = ("Per-panel lettering allocation", "Lettering:", "【唯一可見文字", "【文字",
            "文字必須", "\n文字1", "\n文字 1")
    boundaries = [visual.find(marker) for marker in ends if marker in visual]
    if boundaries:
        visual = visual[:min(boundaries)]
    return visual


def assert_clean_visual_prompt(prompt: str, source_texts: list[str] | None = None) -> None:
    """Inspect actual submitted bytes, including legacy prompts outside this compiler."""
    if len(prompt) > MAX_PROMPT:
        raise CompileError("actual prompt exceeds 8000 characters")
    visual = visual_prompt_section(prompt)
    if visual is None:
        return
    if re.search(r"[「『]", visual):
        raise CompileError("actual prompt visual section contains raw speech quotation; compile drawable fields before generation")
    if any(marker in visual for marker in ("依來源重建", "依原文重建", "待補台詞", "來源缺失")):
        raise CompileError("actual prompt visual section contains production placeholder")
    normalized_visual = _norm(visual)
    for text in source_texts or []:
        normalized_text = _norm(text)
        if len(normalized_text) >= 40 and normalized_text in normalized_visual:
            raise CompileError("actual prompt visual section copies long novel prose")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CompileError(message)


def _inside(root: Path, relative: Any, label: str) -> Path:
    _require(isinstance(relative, str) and relative.strip(), f"{label} missing path")
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CompileError(f"{label} escapes root: {relative}") from exc
    _require(candidate.is_file(), f"{label} missing file: {relative}")
    return candidate


def _sha256(path: Path) -> str:
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    cached = _HASH_CACHE.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    _HASH_CACHE[key] = digest
    return digest


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CompileError(f"invalid UTF-8 JSON: {path}") from exc


def _norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split())


def _range_ids(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    if not isinstance(value, str) or not value.strip():
        return []
    value = value.strip()
    if "-" not in value:
        return [value]
    start, end = value.rsplit("-", 1)
    start_match = _PARAGRAPH_ID.fullmatch(start)
    end_match = _PARAGRAPH_ID.fullmatch(end)
    if not start_match or not end_match:
        return []
    start_prefix = start_match.group("prefix")
    end_prefix = end_match.group("prefix")
    if end_prefix and end_prefix != start_prefix:
        # Real source ranges abbreviate the end within the same unit, e.g.
        # chapter325:p0024-p0025.  A repeated full prefix is also valid.
        unit_prefix = start_prefix.rsplit(":", 1)[0] + ":" if ":" in start_prefix else ""
        local_prefix = start_prefix[len(unit_prefix):]
        if end_prefix == local_prefix:
            end_prefix = start_prefix
        else:
            return []
    first = int(start_match.group("num"))
    last = int(end_match.group("num"))
    if last < first or last - first > 1000:
        return []
    width = len(start_match.group("num"))
    return [f"{start_prefix}{number:0{width}d}" for number in range(first, last + 1)]


def _validate_source(spec: dict[str, Any], source_map: dict[str, Any], root: Path) -> tuple[set[str], str]:
    source_path = source_map.get("source_path")
    _require(spec.get("source_path") == source_path, "spec/source-map source_path mismatch")
    source_file = _inside(root, source_path, "source")
    expected = source_map.get("source_sha256")
    _require(isinstance(expected, str) and len(expected) == 64, "source map missing source_sha256")
    _require(spec.get("source_sha256") == expected, "spec/source-map source_sha256 mismatch")
    _require(_sha256(source_file) == expected, "stale source_sha256")
    source = _load_json(source_file)
    paragraphs = source.get("paragraphs") if isinstance(source, dict) else None
    _require(isinstance(paragraphs, list), "source missing paragraphs")
    ids: set[str] = set()
    prose: list[str] = []
    for paragraph in paragraphs:
        _require(isinstance(paragraph, dict), "invalid source paragraph")
        pid, text = paragraph.get("id"), paragraph.get("text")
        _require(isinstance(pid, str) and pid and isinstance(text, str), "invalid source paragraph")
        _require(pid not in ids, f"duplicate source paragraph id: {pid}")
        ids.add(pid)
        prose.append(text)
    return ids, _norm("".join(prose))


def _validate_references(refs: dict[str, Any], root: Path) -> dict[int, dict[str, Any]]:
    entries = refs.get("references")
    _require(isinstance(entries, list), "references must be a list")
    _require(len(entries) <= MAX_REFERENCES, "more than 5 references")
    by_index: dict[int, dict[str, Any]] = {}
    for entry in entries:
        _require(isinstance(entry, dict), "invalid reference entry")
        index = entry.get("index")
        _require(isinstance(index, int) and index > 0 and index not in by_index, "invalid reference index")
        use_only = entry.get("use_only")
        _require(isinstance(use_only, str) and use_only.strip(), f"reference {index} missing use_only")
        path = _inside(root, entry.get("path"), f"reference {index}")
        expected = entry.get("sha256")
        _require(isinstance(expected, str) and len(expected) == 64, f"reference {index} missing sha256")
        _require(_sha256(path) == expected, f"stale reference sha256: {index}")
        by_index[index] = entry
    _require(sorted(by_index) == list(range(1, len(entries) + 1)), "reference indexes must be contiguous from 1")
    return by_index


def _style_lines(style: Any) -> list[str]:
    if style is None:
        return ["polished Japanese full-color manga; clean expressive linework; cinematic natural lighting"]
    if isinstance(style, str):
        _require(bool(style.strip()), "style is empty")
        return [style.strip()]
    _require(isinstance(style, dict), "style must be a string or object")
    lines = []
    for key in _STYLE_KEYS:
        value = style.get(key)
        if value is not None:
            _require(isinstance(value, str) and value.strip(), f"invalid style.{key}")
            lines.append(f"{key}: {value.strip()}")
    _require(bool(lines), "style has no whitelisted fields")
    return lines


def compile_prompt(
    spec: dict[str, Any], refs: dict[str, Any], source_map: dict[str, Any], root: str | Path
) -> str:
    """Validate contracts and return the exact prompt; never infer source attribution."""
    _require(isinstance(spec, dict) and isinstance(refs, dict) and isinstance(source_map, dict), "inputs must be objects")
    root_path = Path(root)
    prompt_format = source_map.get("prompt_format", "source-map-compiler-v1")
    _require(prompt_format in {"source-map-compiler-v1", "panel-lettering-v2"}, "unknown prompt_format")
    panel_lettering = prompt_format == "panel-lettering-v2"
    if panel_lettering:
        _require(bool(source_map.get("episode")) and spec.get("episode") == source_map["episode"],
                 "spec/source-map episode mismatch")
    paragraph_ids, normalized_source = _validate_source(spec, source_map, root_path)
    references = _validate_references(refs, root_path)

    intent = spec.get("intent")
    _require(intent in {"generate", "edit"}, "intent must be generate or edit")
    if intent == "edit":
        _require(spec.get("artwork_identity_and_speakers_correct") is True,
                 "edit requires artwork_identity_and_speakers_correct=true; use generate for a wrong speaker/person")
    materials = source_map.get("materials")
    if intent == "generate":
        _require(isinstance(materials, dict), "generate source map missing materials")
    strict_identity = source_map.get("identity_bindings_required") is True
    definitions = source_map.get("character_definitions", {})
    _require(not strict_identity or isinstance(definitions, dict), "character_definitions must be an object")
    identity_lines: dict[tuple[str, int], str] = {}
    subject_owners: dict[tuple[str, str], str] = {}

    panels = spec.get("panels")
    texts = spec.get("texts", [])
    dialogues = source_map.get("dialogues")
    _require(isinstance(panels, list) and panels, "panels missing")
    _require(isinstance(texts, list), "texts must be a list")
    _require(isinstance(dialogues, dict), "source map dialogues missing")

    panel_by_number: dict[int, dict[str, Any]] = {}
    unused_offscreen: dict[int, set[str]] = {}
    panel_lines: list[str] = []
    for panel in panels:
        _require(isinstance(panel, dict), "invalid panel")
        number = panel.get("panel")
        _require(isinstance(number, int) and number > 0 and number not in panel_by_number, "invalid panel number")
        participants = panel.get("participants")
        anonymous = panel.get("anonymous_participants", [])
        offscreen = panel.get("offscreen_speakers", {})
        mapping = panel.get("reference_indexes")
        _require(isinstance(participants, list) and all(isinstance(x, str) and x for x in participants),
                 f"panel {number} participants invalid")
        _require(len(participants) == len(set(participants)), f"panel {number} duplicate participant")
        _require(isinstance(anonymous, list) and all(isinstance(x, str) and x for x in anonymous),
                 f"panel {number} anonymous_participants invalid")
        _require(isinstance(offscreen, dict), f"panel {number} offscreen_speakers invalid")
        for name, direction in offscreen.items():
            _require(isinstance(name, str) and name and isinstance(direction, str)
                     and 0 < len(direction) <= 60,
                     f"panel {number} offscreen speaker/direction invalid")
            _require(name not in participants, f"panel {number} offscreen speaker is visibly present: {name}")
        _require(set(anonymous).issubset(set(participants)), f"panel {number} anonymous participant not declared in participants")
        _require(isinstance(mapping, dict), f"panel {number} reference_indexes missing")
        for person in participants:
            if person in anonymous:
                continue
            _require(person in mapping and mapping[person] is not None,
                     f"panel {number} named participant missing reference: {person}")
            _require(mapping[person] in references, f"panel {number} unknown reference for {person}")
            if intent == "generate":
                allowed = materials.get(person)
                _require(isinstance(allowed, list) and allowed
                         and all(isinstance(value, str) and len(value) == 64 for value in allowed),
                         f"panel {number} named participant missing material binding: {person}")
                chosen_sha = references[mapping[person]]["sha256"]
                _require(chosen_sha in allowed,
                         f"panel {number} reference is not allowed for character: {person}")
            if strict_identity:
                definition = definitions.get(person)
                _require(isinstance(definition, dict), f"missing fixed character definition: {person}")
                state_id, appearance = definition.get("state_id"), definition.get("appearance")
                _require(isinstance(state_id, str) and 0 < len(state_id) <= 80,
                         f"missing short character state_id: {person}")
                _require(isinstance(appearance, str) and 0 < len(appearance) <= 220
                         and not _RAW_SPEECH.search(appearance),
                         f"missing concise visual character definition: {person}")
                reference = references[mapping[person]]
                subjects = reference.get("identity_subjects", {})
                locator = subjects.get(person) if isinstance(subjects, dict) else None
                _require(isinstance(locator, str) and 0 < len(locator) <= 120
                         and not _RAW_SPEECH.search(locator),
                         f"reference subject must explicitly identify character: {person}")
                subject_key = (reference["sha256"], _norm(locator))
                previous = subject_owners.get(subject_key)
                _require(previous in (None, person),
                         f"same reference subject assigned to different characters: {person}")
                subject_owners[subject_key] = person
                identity_lines[(person, mapping[person])] = (
                    f"{person}: state={state_id}; appearance={appearance}; "
                    f"identity source=Reference {mapping[person]}, subject={locator}. "
                    "Keep this identity distinct; never borrow another actor's face, ears, age or costume."
                )
        action = panel.get("action")
        _require(isinstance(action, str) and action.strip(), f"panel {number} action missing")
        _require(len(action) <= MAX_ACTION, f"panel {number} action exceeds 220 characters")
        _require(not _RAW_SPEECH.search(action), f"panel {number} action contains raw novel speech quotation")
        normalized_action = _norm(action)
        _require(len(normalized_action) < 40 or normalized_action not in normalized_source,
                 f"panel {number} action copies long source prose")
        visual = []
        for field in ("scene", "participants", "anonymous_participants", "positions", "action", "state"):
            if field in panel:
                value = panel[field]
                if isinstance(value, list):
                    value = ", ".join(value)
                _require(isinstance(value, str), f"panel {number} invalid {field}")
                visual.append(f"{field}={value}")
        ref_uses = ", ".join(
            f"{name}->ref {mapping[name]}"
            for name in participants
            if name not in anonymous and name in mapping and mapping[name] is not None
        )
        if ref_uses:
            visual.append(f"identity_refs={ref_uses}")
        panel_lines.append(f"Panel {number}: " + "; ".join(visual))
        panel_by_number[number] = panel
        unused_offscreen[number] = set(offscreen)

    visible_count = 0
    text_lines: list[str] = []
    lettering_by_panel: dict[int, list[int]] = {number: [] for number in panel_by_number}
    for item in texts:
        _require(isinstance(item, dict), "invalid text item")
        number = item.get("panel")
        _require(number in panel_by_number, "text references missing panel")
        text = item.get("text")
        placement = item.get("placement")
        supplied_speaker = item.get("speaker")
        _require(isinstance(text, str) and text and isinstance(placement, str) and placement,
                 f"panel {number} text/placement missing")
        visible_count += len(text)
        dialogue_id = item.get("dialogue_id")
        if supplied_speaker == "旁白" and dialogue_id in (None, ""):
            speaker = "旁白"
            _require(item.get("tail_target") in (None, "", "none"), "narration must have no tail")
            tail = "no tail"
        else:
            _require(isinstance(dialogue_id, str) and dialogue_id, "spoken text missing dialogue_id")
            entry = dialogues.get(dialogue_id)
            _require(isinstance(entry, dict), f"missing source-map dialogue: {dialogue_id}")
            speaker = entry.get("speaker")
            _require(isinstance(speaker, str) and speaker, f"dialogue {dialogue_id} missing speaker")
            _require(supplied_speaker == speaker, f"dialogue {dialogue_id} speaker mismatch: expected {speaker}")
            panel = panel_by_number[number]
            onscreen = speaker in panel["participants"]
            offscreen = panel.get("offscreen_speakers", {})
            _require(onscreen or speaker in offscreen,
                     f"dialogue {dialogue_id} speaker absent from panel {number} and not explicitly offscreen")
            evidence_ids = _range_ids(entry.get("source_range"))
            _require(isinstance(entry.get("basis"), str) and entry["basis"].strip(),
                     f"dialogue {dialogue_id} missing attribution basis")
            _require(bool(evidence_ids) and all(pid in paragraph_ids for pid in evidence_ids),
                     f"dialogue {dialogue_id} missing attribution source paragraph IDs")
            tail_target = item.get("tail_target")
            _require(isinstance(tail_target, str) and 0 < len(tail_target) <= 60 and tail_target != "none",
                     f"dialogue {dialogue_id} missing short-tail destination")
            if onscreen:
                _require(speaker in tail_target,
                         f"dialogue {dialogue_id} tail destination does not match speaker {speaker}")
                tail = f"short tail to {speaker}'s mouth"
            else:
                direction = offscreen[speaker]
                normalized_tail = _norm(tail_target)
                normalized_direction = _norm(direction)
                _require(normalized_tail in normalized_direction or normalized_direction in normalized_tail,
                         f"dialogue {dialogue_id} tail destination does not match offscreen direction")
                unused_offscreen[number].discard(speaker)
                tail = f"short tail towards offscreen direction: {direction}; do not draw {speaker}"
        order = item.get("order")
        _require(isinstance(order, int) and order > 0, f"panel {number} text order missing")
        if panel_lettering:
            _require(order not in lettering_by_panel[number], f"panel {number} duplicate text order")
        lettering_by_panel[number].append(order)
        text_lines.append(
            f'Text {order} in panel {number}: exact Traditional Chinese lettering "{text}"; '
            f"speaker={speaker}; placement={placement}; {tail}"
        )
    for number, speakers in unused_offscreen.items():
        if speakers:
            raise CompileError(
                f"panel {number} offscreen speaker not backed by authoritative dialogue: {sorted(speakers)[0]}"
            )
    _require(visible_count <= MAX_VISIBLE_TEXT, "visible text exceeds 90 characters")

    allocation: list[str] = []
    if panel_lettering:
        allocation = [
            "Per-panel lettering allocation (do not improvise dialogue from gestures or scene descriptions):",
            "Every listed text appears exactly once in its assigned panel. No invented dialogue, thoughts, signs or sound-effect lettering.",
        ]
        for number, orders in lettering_by_panel.items():
            if orders:
                names = ", ".join(f"Text {order}" for order in orders)
                allocation.append(f"Panel {number}: ONLY {names}; exactly {len(orders)} lettering containers; no additional text.")
            else:
                allocation.append(f"Panel {number}: SILENT; NO VISIBLE TEXT, speech bubbles, thought bubbles or caption boxes.")

    ref_lines = [f"Reference {idx}, use only: {references[idx]['use_only']}" for idx in sorted(references)]
    prompt = "\n".join([
        f"Create a {intent} comic page in portrait 1024x1536, full color, native lettering, all ages.",
        "Render only the exact closed Traditional Chinese text listed below; add no other visible text.",
        "Use fixed manga reading order: right-to-left within each row, then top-to-bottom.",
        "Use white speech bubbles and brief cream caption boxes. Ignore all text, labels, and view grids in references.",
        "Draw only the actors listed for each panel; do not add background characters.",
        "Style:",
        *_style_lines(spec.get("style")),
        "References:",
        *ref_lines,
        *(["Fixed character identities:", *identity_lines.values()] if strict_identity else []),
        "Visual panels:",
        *panel_lines,
        *allocation,
        "Lettering:",
        *text_lines,
    ])
    _require(len(prompt) <= MAX_PROMPT, "compiled prompt exceeds 8000 characters")
    return prompt


def compile_batch(batch: dict[str, Any], root: Path) -> dict[str, Any]:
    """Compile a whole-volume list once; validate all inputs before writing any prompt."""
    units = batch.get("units")
    _require(isinstance(units, list) and units, "batch units missing")
    pending = []
    ids, destinations = set(), set()
    for unit in units:
        source_map = _load_json(_inside(root, unit.get("source_map"), "source map"))
        if batch.get("require_identity_bindings") is True:
            _require(source_map.get("identity_bindings_required") is True,
                     "new batch requires fixed character identity bindings in every source map")
        pages = unit.get("pages")
        _require(isinstance(pages, list) and pages, "batch pages missing")
        for page in pages:
            spec = _load_json(_inside(root, page.get("spec"), "spec"))
            refs = _load_json(_inside(root, page.get("references"), "references"))
            key = spec.get("id")
            _require(isinstance(key, str) and key and key not in ids, "duplicate/missing batch page identity")
            _require(isinstance(page.get("out"), str) and page["out"], "batch output missing")
            output = (root / page["out"]).resolve()
            try:
                output.relative_to(root.resolve())
            except ValueError as exc:
                raise CompileError("batch output escapes root") from exc
            _require(output not in destinations, "overlapping batch output")
            ids.add(key)
            destinations.add(output)
            pending.append((key, output, compile_prompt(spec, refs, source_map, root)))
    rows = []
    for key, output, prompt in pending:
        raw = prompt.encode("utf-8")
        unchanged = output.is_file() and output.read_bytes() == raw
        if not unchanged:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(raw)
        rows.append({"id": key, "out": output.relative_to(root.resolve()).as_posix(),
                     "status": "unchanged" if unchanged else "written",
                     "characters": len(prompt), "prompt_sha256": hashlib.sha256(raw).hexdigest()})
    return {"ok": True, "compiled": len(rows), "pages": rows, "images_generated": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--references", type=Path)
    parser.add_argument("--source-map", type=Path)
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    try:
        if args.batch:
            _require(not any((args.spec, args.references, args.source_map)), "batch and single-page arguments are exclusive")
            receipt = compile_batch(_load_json(args.batch), args.root)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"ok": True, "compiled": receipt["compiled"], "report": str(args.out)}))
            return 0
        _require(all((args.spec, args.references, args.source_map)), "provide spec/references/source-map or batch")
        spec = _load_json(args.spec)
        refs = _load_json(args.references)
        source_map = _load_json(args.source_map)
        prompt = compile_prompt(spec, refs, source_map, args.root)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(prompt, encoding="utf-8", newline="")
        receipt = {
            "ok": True,
            "out": str(args.out),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "characters": len(prompt),
        }
        print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))
        return 0
    except CompileError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
