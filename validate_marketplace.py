#!/usr/bin/env python3
"""Validate this marketplace against the agentskills.io spec and the contest rules.

    python3 validate_marketplace.py

Standard library only, so it runs anywhere the skills themselves run.
Exits non-zero on any error. Warnings do not fail the build.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")   # no leading/trailing/double hyphen
MAX_NAME, MAX_DESC, MAX_COMPAT, MAX_LINES = 64, 1024, 500, 500

errors, warnings = [], []


def err(m):
    errors.append(m)


def warn(m):
    warnings.append(m)


def parse_frontmatter(text):
    """Minimal YAML frontmatter reader: scalars, folded (>-) and literal (|) blocks.

    ponytail: covers exactly the subset the spec allows in a SKILL.md header;
    swap for PyYAML only if a skill ever needs nested structures.
    """
    if not text.startswith("---"):
        return None, "file does not start with '---' frontmatter"
    end = text.find("\n---", 3)
    if end == -1:
        return None, "frontmatter is not terminated by '---'"
    body = text[3:end].strip("\n")
    data, key, buf, indent = {}, None, [], None
    for raw in body.split("\n"):
        if key and (raw.startswith((" ", "\t")) or not raw.strip()):
            if raw.strip():
                if indent is None:
                    indent = len(raw) - len(raw.lstrip())
                buf.append(raw.strip())
            continue
        if key:
            data[key] = " ".join(buf).strip()
            key, buf, indent = None, [], None
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if v in (">", ">-", "|", "|-", ""):
            key = k
        else:
            data[k] = v.strip("'\"")
    if key:
        data[key] = " ".join(buf).strip()
    return data, None


def check_skill(skill_id, path):
    full = os.path.join(ROOT, path)
    if not os.path.isdir(full):
        return err(f"{skill_id}: path does not exist: {path}")
    md = os.path.join(full, "SKILL.md")
    if not os.path.isfile(md):
        return err(f"{skill_id}: no SKILL.md at {path}")

    text = open(md, encoding="utf-8").read()
    fm, perr = parse_frontmatter(text)
    if perr:
        return err(f"{skill_id}: {perr}")

    name = fm.get("name", "")
    if not name:
        err(f"{skill_id}: frontmatter is missing required field 'name'")
    else:
        if len(name) > MAX_NAME:
            err(f"{skill_id}: name is {len(name)} chars (max {MAX_NAME})")
        if not NAME_RE.match(name):
            err(f"{skill_id}: name {name!r} must be lowercase alphanumerics and single "
                f"hyphens, not starting or ending with a hyphen")
        if name != os.path.basename(path.rstrip("/")):
            err(f"{skill_id}: name {name!r} must match its directory name "
                f"{os.path.basename(path)!r}")
        if name != skill_id:
            err(f"{skill_id}: marketplace id does not match SKILL.md name {name!r}")

    desc = fm.get("description", "")
    if not desc:
        err(f"{skill_id}: frontmatter is missing required field 'description'")
    elif len(desc) > MAX_DESC:
        err(f"{skill_id}: description is {len(desc)} chars (max {MAX_DESC})")
    elif len(desc) < 60:
        warn(f"{skill_id}: description is short ({len(desc)} chars); it should say "
             f"what the skill does AND when to use it")
    elif " when " not in desc.lower() and "use when" not in desc.lower():
        warn(f"{skill_id}: description should state when to use the skill")

    compat = fm.get("compatibility", "")
    if compat and len(compat) > MAX_COMPAT:
        err(f"{skill_id}: compatibility is {len(compat)} chars (max {MAX_COMPAT})")

    lines = text.count("\n") + 1
    if lines > MAX_LINES:
        err(f"{skill_id}: SKILL.md is {lines} lines (keep under {MAX_LINES}; move "
            f"detail into references/)")

    # every referenced file must exist -- a dead reference is a silent failure
    # (?<![\w/]) so a path inside a longer one -- $S/other-skill/scripts/x.py --
    # is not mistaken for a reference relative to THIS skill.
    for ref in re.findall(r"(?<![\w/])((?:references|scripts|assets)/[A-Za-z0-9_./-]+)", text):
        ref = ref.rstrip(".,);:`")
        if not os.path.exists(os.path.join(full, ref)):
            err(f"{skill_id}: SKILL.md references {ref} which does not exist")

    for sub in ("scripts", "references"):
        d = os.path.join(full, sub)
        if os.path.isdir(d) and not os.listdir(d):
            warn(f"{skill_id}: {sub}/ exists but is empty")
    return None


def main():
    mpath = os.path.join(ROOT, "marketplace.json")
    if not os.path.isfile(mpath):
        print("FAIL: no marketplace.json at the marketplace root")
        return 1
    try:
        m = json.load(open(mpath, encoding="utf-8"))
    except Exception as e:
        print(f"FAIL: marketplace.json is not valid JSON: {e}")
        return 1

    for k in ("name", "version", "skills"):
        if k not in m:
            err(f"marketplace.json is missing required key: {k}")
    skills = m.get("skills", [])
    if not skills:
        err("marketplace.json lists no skills")

    entries = [s for s in skills if s.get("entrypoint")]
    if len(entries) != 1:
        err(f"marketplace.json must mark exactly one entrypoint, found {len(entries)}")

    ids = [s.get("id") for s in skills]
    if len(ids) != len(set(ids)):
        err("marketplace.json contains duplicate skill ids")

    for s in skills:
        if not s.get("id") or not s.get("path"):
            err(f"marketplace.json skill entry missing id or path: {s}")
            continue
        check_skill(s["id"], s["path"])

    # every skill folder on disk must be declared, or it ships unlisted
    sk_dir = os.path.join(ROOT, "skills")
    if os.path.isdir(sk_dir):
        declared = {os.path.basename(s.get("path", "").rstrip("/")) for s in skills}
        for d in sorted(os.listdir(sk_dir)):
            if os.path.isdir(os.path.join(sk_dir, d)) and d not in declared:
                err(f"skills/{d} exists on disk but is not listed in marketplace.json")

    if not os.path.isfile(os.path.join(ROOT, "README.md")):
        err("no README.md at the marketplace root")

    # every bundled script must at least parse (syntax check, no bytecode written)
    for dirpath, _, files in os.walk(os.path.join(ROOT, "skills")):
        for f in sorted(files):
            if f.endswith(".py"):
                p = os.path.join(dirpath, f)
                try:
                    compile(open(p, encoding="utf-8").read(), p, "exec")
                except SyntaxError as e:
                    err(f"{os.path.relpath(p, ROOT)} does not compile: {e}")

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    if errors:
        print(f"\nFAIL: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"\nOK: {len(skills)} skills, 1 entrypoint, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
