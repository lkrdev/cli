---
name: lookml
description: >
  LookML syntax and authoring reference (`looker-open-source/looker-skills`).
  Provides sub-skills for LookML models, views, derived tables, explores, joins,
  fields (dimensions, dimension groups, measures, filters, parameters, value formats),
  refinements, Liquid variables, sets, access grants, and LookML data tests.
---

# LookML Reference (`lookml`)

> **Scope note:** Authoring or modifying `drill_fields:` (and drill-only `set:` blocks) is **out of scope for now**. Do not add unrequested `drill_fields:` when generating or refining LookML, and do not flag missing drill paths during reviews.

Index of LookML authoring sub-skills from [looker-open-source/looker-skills](https://github.com/looker-open-source/looker-skills) located in `sub-skills/*/SKILL.md`:

| Sub-skill | Reference files | Description |
| :--- | :--- | :--- |
| [lookml-model](sub-skills/lookml-model/SKILL.md) | None | Use this skill when you need to create or modify a LookML Model file (`.model.lkml`). This includes defining connections, includes, and configuring model-level settings. |
| [lookml-view](sub-skills/lookml-view/SKILL.md) | [derived_table.md](sub-skills/lookml-view/references/derived_table.md) | Use this skill to create or modify LookML Views. Covers basic view definitions, `sql_table_name`, file organization, and patterns. |
| [lookml-explore](sub-skills/lookml-explore/SKILL.md) | [joins.md](sub-skills/lookml-explore/references/joins.md), [advanced.md](sub-skills/lookml-explore/references/advanced.md) | Use this skill when you need to create or modify a LookML Explore. This includes defining the Explore, joins, access grants, and basic configuration. |
| [lookml-fields](sub-skills/lookml-fields/SKILL.md) | [dimension.md](sub-skills/lookml-fields/references/dimension.md), [dimension_group.md](sub-skills/lookml-fields/references/dimension_group.md), [measure.md](sub-skills/lookml-fields/references/measure.md), [filter_parameter.md](sub-skills/lookml-fields/references/filter_parameter.md), [value_format.md](sub-skills/lookml-fields/references/value_format.md) | Overview of LookML field types (Dimension, Measure, Filter, Parameter) and the role of the `sql` parameter in each. Use this skill to choose the right field type for your data modeling needs. |
| [lookml-refinements](sub-skills/lookml-refinements/SKILL.md) | None | Deep dive into LookML includes, refinements (layering), and project structure best practices. Essential for mastering Looker's object-oriented capabilities. |
| [lookml-liquid](sub-skills/lookml-liquid/SKILL.md) | None | Use this skill to use Liquid variables in LookML for dynamic SQL, HTML, and Links, including advanced patterns for query optimization. |
| [lookml-advanced-liquid](sub-skills/lookml-advanced-liquid/SKILL.md) | None | Advanced LookML Liquid compiler patterns: `{{ _table }}`, `{{ _view._name }}`, `{{ field._sql }}`, `{{ view.field._sql }}`, `(${EXTENDED})`, aliased bare joins (`_sdt_*`), NDTs with `cancel_grouping_fields:` vs. `{{ measure._sql }}`, and Bronze/Silver/Gold DRY inheritance rules. |
| [lookml-ojof](sub-skills/lookml-ojof/SKILL.md) | None | Design, build, refactor, and optimize multi-fact LookML Explores using the Outer Join On False (OJOF) pattern (`from: none`, `type: full_outer` with `sql_on: FALSE ;;`, Liquid `_in_query` `COALESCE` shared dimensions, and `UNNEST([COALESCE(...)])` co-dimension views). |
| [lookml-sets](sub-skills/lookml-sets/SKILL.md) | None | Guide to using LookML sets for grouping fields, controlling visibility, and managing drill paths. |
| [lookml-access-grants](sub-skills/lookml-access-grants/SKILL.md) | None | Use this skill to create Access Grants for row-level or object-level security. |
| [lookml-tests](sub-skills/lookml-tests/SKILL.md) | None | Standards and best practices for writing LookML tests to ensure data integrity, accuracy, and logic validation. |
