# Candidate Evidence Profile Schema (Private)

The candidate evidence profile is private input for the resume-tailoring
workflow. Codex creates it from user-supplied files. The renderer validates
the profile but never guesses facts.

Source documents and candidate profiles stay outside the shareable Skill
package.

## Version

`schema_version` is required and must be the integer `1`. Versions other than
`1` are rejected, not migrated.

## Top-level fields

| Field | Type |
| --- | --- |
| `schema_version` | integer (`1`) |
| `identity` | object |
| `education` | array |
| `employment` | array |
| `projects` | array |
| `skills` | array |
| `evidence` | array |
| `unresolved` | array |

## Evidence records

Each `evidence` item is an object with:

| Field | Type | Requirement |
| --- | --- | --- |
| `evidence_id` | string | Nonempty and unique across the profile. |
| `status` | string | Exactly one of `verified`, `partial`, `conflict`, or `missing`. |
| `sources` | array | Nonempty for every status. Each source is an object with nonempty string `file` and `location`. |

## Unresolved records

`unresolved` records facts that cannot be resolved from the user-supplied
sources. Each record is an object with `field`, `reason`, `candidates`, and
`source_evidence_ids`, preserving both the conflicting values and their
evidence links.

```json
{
  "field": "employment[0].dates",
  "reason": "Two source files contain different start months",
  "candidates": ["2024-03", "2024-04"],
  "source_evidence_ids": ["employment-date-001", "employment-date-002"]
}
```
