"""
QA Agent — 2-layer quality assurance for Shorts and their packaging.

Layer 1: Content Coherence (per Short)
  - Clear opening hook? (1-10)
  - Develops ONE coherent idea? (1-10)
  - Ends on complete thought? (1-10)
  - Standalone comprehension? (yes/no + explanation)
  - Total coherence score: sum of 3 scores / 30

Layer 2: Package Alignment
  - Title matches content? (yes/no)
  - Description accurate? (yes/no)
  - Tags relevant? (yes/no)
  - Thumbnail text matches? (yes/no)

Verdict: PASS if coherence >= 21/30 AND all Layer 2 checks pass.
"""
import json
import logging
import os

from agents.base import call_claude_json

logger = logging.getLogger(__name__)

METADATA_DIR = "/opt/yt-editor/data/metadata"
MODEL = "claude-sonnet-4-20250514"
TRANSCRIPT_MAX_CHARS = 8000

SYSTEM_PROMPT = """You are a ruthless quality assurance specialist for YouTube Shorts.
Your job is to catch problems BEFORE content goes live. You have two review layers.

LAYER 1 — CONTENT COHERENCE (per Short):
For each Short, score these three dimensions (1-10 each):
- hook_score: Does it have a clear, compelling opening hook in the first 3 seconds?
  10 = instantly gripping, 1 = no hook at all
- coherence_score: Does it develop ONE coherent idea from start to finish?
  10 = crystal clear single idea, 1 = jumbled mess of half-ideas
- completion_score: Does it end on a complete thought?
  10 = satisfying conclusion, 1 = cuts off mid-sentence

Also answer:
- standalone_understood (bool): Would a viewer who sees ONLY this clip understand it?
- standalone_explanation (string): Why or why not? Be specific.

Total coherence = hook_score + coherence_score + completion_score (out of 30)

LAYER 2 — PACKAGE ALIGNMENT (per Short):
- title_matches (bool): Does the title accurately represent the Short's content?
- description_matches (bool): Does the description accurately describe the Short?
- tags_relevant (bool): Are the tags relevant to the Short's specific content?
- thumbnail_text_matches (bool): Does the thumbnail text concept match the Short?

VERDICT:
- PASS: total coherence >= 21 AND all 4 Layer 2 checks are true
- FAIL: anything else

For FAIL verdicts, provide:
- issues (list of strings): specific problems found
- suggestions (list of strings): concrete fixes

Return a JSON object with:
- shorts (list): one per Short, each has:
  - index (int): 0-based index
  - hook_score (int 1-10)
  - coherence_score (int 1-10)
  - completion_score (int 1-10)
  - total_coherence (int): sum of the three scores
  - standalone_understood (bool)
  - standalone_explanation (string)
  - title_matches (bool)
  - description_matches (bool)
  - tags_relevant (bool)
  - thumbnail_text_matches (bool)
  - verdict (string): "PASS" or "FAIL"
  - issues (list of strings): empty if PASS
  - suggestions (list of strings): empty if PASS
- overall_pass (bool): true only if ALL Shorts pass
- flagged_shorts (list of ints): indices of Shorts that failed

Be HONEST. Do not rubber-stamp weak content. A FAIL now saves embarrassment later.
Return ONLY valid JSON."""


def run(short_designs: list, package_result: dict, transcript_text: str, job_id: str) -> dict:
    """Run 2-layer QA on Short designs and their packaging."""
    logger.info(f"[qa] Running QA for job {job_id} — {len(short_designs)} Shorts")

    truncated = transcript_text[:TRANSCRIPT_MAX_CHARS]
    if len(transcript_text) > TRANSCRIPT_MAX_CHARS:
        truncated += "\n\n[TRANSCRIPT TRUNCATED]"

    # Build per-Short review pairs (design + package)
    shorts_for_review = []
    package_shorts = package_result.get("shorts", [])
    for i, design in enumerate(short_designs):
        pkg = package_shorts[i] if i < len(package_shorts) else {}
        shorts_for_review.append({
            "index": i,
            "design": design,
            "package": pkg,
        })

    prompt = f"""Review these YouTube Shorts for quality.

SHORTS TO REVIEW:
{json.dumps(shorts_for_review, indent=2)[:5000]}

TRANSCRIPT (for context):
{truncated}

Run both Layer 1 (Content Coherence) and Layer 2 (Package Alignment) checks
on each Short. Be rigorous — a FAIL now prevents a bad Short from going live.

Return the complete QA JSON."""

    result = call_claude_json(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        model=MODEL,
        max_tokens=4000,
        temperature=0.2,
    )

    # Ensure structural integrity of the result
    if "shorts" not in result:
        result = {"shorts": result if isinstance(result, list) else [], "overall_pass": False, "flagged_shorts": []}

    if "overall_pass" not in result:
        result["overall_pass"] = all(
            s.get("verdict") == "PASS" for s in result.get("shorts", [])
        )

    if "flagged_shorts" not in result:
        result["flagged_shorts"] = [
            s.get("index", i) for i, s in enumerate(result.get("shorts", []))
            if s.get("verdict") != "PASS"
        ]

    # Save to disk
    os.makedirs(METADATA_DIR, exist_ok=True)
    out_path = os.path.join(METADATA_DIR, f"{job_id}_qa.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"[qa] Saved QA results to {out_path} — overall_pass={result['overall_pass']}")

    return result
run_qa_agent = run
