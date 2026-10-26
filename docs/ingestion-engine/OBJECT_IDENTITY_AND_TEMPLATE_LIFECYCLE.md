# Object identity and template lifecycle contract

**Status:** Requirements captured; physical schema and migrations not implemented.
**Updated:** September 30, 2026

This document records the object identity and deletion requirements for the
Parallel Ingestion Engine. It is a design input for the physical model and
import coordinator, not evidence that runtime v2 implements these behaviors.

## Identity model

1. **An Object Template defines an object type; it is not an instance.** It is
   the user-named shell/creator (for example, Employee or another type) that
   selects report templates, properties, identifier bindings and match
   relationships. The design must not hard-code Employee as the only type.
2. **Ingestion creates or resolves instances from report rows.** Each
   qualifying row can create a distinct instance when creation is authorized,
   or link to an existing instance when configured Strong Identifiers match.
   Different identifiers contributed by multiple report templates can resolve
   to and attach to the same instance UUID.
3. **Every object instance receives a system-generated UUID.** Generate it
   when ingestion creates that instance, keep it stable for its lifetime, and
   use it as the key for its properties, source facts, identifiers and
   relationships. Never derive it from a source field.
4. **Keep the engine's physical model independent of legacy Employee identity.**
   The engine owns its UUID and tables. It must not assume that the new UUID is
   `workers.worker_id` or `dim_employee.employee_key`, nor write those legacy
   tables as a side effect of importing an engine object.
5. **Source Strong Identifiers are business keys, not the object's UUID.** A
   report template can contribute one or more Strong Identifier fields. Their
   definitions are attached to the Object Template through explicit
   associations; their imported values are stored with their normalized value,
   identifier type, source/template/field provenance and the object's UUID.
6. **Strong Identifier associations can be attached, detached, or deleted.**
   Detaching a template field removes its authority as an active matching key.
   Deleting a Strong Identifier removes the relevant active configuration and
   owned value rows after dependency validation. Neither action changes the
   object's UUID.
7. **Create/evolve schema per object type, not per instance.** An approved
   Object Template defines the physical shape for its object type. Build its
   schema once and version its changes; never run DDL or create a table for
   every employee, row or file. Keep shared identity, identifier and
   source-fact structures generic so other user-defined types can use them.
8. **All instance properties point to the instance UUID.** Store physical
   properties, identifier values and source facts in engine-owned tables joined
   by that UUID. Any new structure needs a versioned migration, foreign keys and
   documented ownership.
9. **An Object Template may use multiple report templates.** Source membership,
   field/property mappings and Strong Identifier bindings must be represented
   separately so one source template can be removed without silently deleting
   data owned by the other sources.

## Canonical property composition and cross-object relationships

The Object Template defines a canonical type and schema. It also lets an
administrator compose each canonical property from fields in one or more
linked report templates.

- A canonical property is a governed target such as `first_name`,
  `last_name`, or `vendor_uuid`.
- A mapping connects a pinned report-template version and `field_key` to a
  canonical property, with any approved transform, source authority/priority,
  and validity rule.
- Multiple report fields may feed the same canonical property. The Object
  Template must define which source wins or how values are combined. Do not
  silently overwrite one report's value with another's. Preserve each source
  value and mapping lineage; report conflicting values for review.
- Property composition is separate from identity resolution. Strong
  Identifiers decide whether rows from different reports describe the same
  instance; property mappings decide which values populate that instance.
  Ambiguous identity matches must not merge instances.
- The model supports multiple object types, each with its own properties,
  report-template set and Strong Identifier graph. For example, `Employee` and
  `Vendor` instances have independent UUIDs and schemas.
- Relationships connect instances across object types. An Employee-to-Vendor
  relationship can map a vendor identifier in an Employee report to a
  Strong Identifier on a Vendor instance. Store the resulting UUID link with
  relationship type, source field, source/template version and evidence.
- Define relationship cardinality and target uniqueness. A missing or
  ambiguous Vendor match must be exposed for review/quarantine; never guess a
  link from a display name when a configured key is expected.
- Imports follow the relationship dependency graph. If Employee rows link to
  Vendors, load or resolve Vendor instances before finalizing those links.

### First vertical slice

Prove the generic model with a bounded Employee/Vendor example:

1. Create a user-named Employee object type connected to two report templates.
2. Configure Strong Identifiers that let their rows resolve to the same
   Employee instance.
3. Map Employee `first_name` from report 1 and `last_name` from report 2;
   retain both source values and their provenance.
4. Create a Vendor object type from a third report template.
5. Link Employee rows to Vendor instances using a configured Vendor Strong
   Identifier, and test unmatched and ambiguous Vendor keys.
6. Verify that many Employee UUIDs can link to one Vendor UUID and that the
   relationship is stored independently from either object's properties.

Field authority/conflict policy and relationship cardinality must be saved in
the Object Template before this slice can safely write canonical rows.

### Engine-owned physical model

Runtime v2 already generates a UUID in `engine_v2_objects.object_id` for each
prototype instance, but that table currently stores only object metadata.
Retain this engine-owned UUID as the instance key and add physical property,
identifier and source-fact tables that reference it. The legacy `worker_id` /
`dim_employee.employee_key` chain remains independent. Cross-linking the two
systems would require a separate, explicit migration contract and is outside
this import slice.

The physical schema strategy still needs a decision: additive migrations for
each object type's defined shape, or shared typed property tables with a
governed field catalog. In either case, schema creation/evolution happens per
object type and template version, never per UUID or uploaded file. Common
identity, identifier and source-fact tables should serve all user-defined types.

## Template removal and cascade behavior

Removing a report template that contributes to an Object Template must use a
preview-and-validate workflow. A direct delete or automatic archive is not a
substitute for this workflow.

1. **Preview impact.** Identify the source template/version, Strong Identifier
   bindings and values, source facts, properties and links that depend on it,
   plus objects that have no remaining supporting source. Show counts and the
   effects of the cascade before accepting the request.
2. **Require Object Template changes first.** If the template contributes
   Strong Identifiers, ask the user to edit the Object Template and detach or
   replace those bindings. Do not delete the source template or its rows yet.
3. **Validate detachment.** Re-read the saved Object Template and validate
   that no active Strong Identifier binding references the template/version
   being removed; all remaining bindings reference live included fields; and
   no surviving object link would be orphaned or invalidated. If any check
   fails, stop and explain what must be changed.
4. **Warn on the last source.** If this is the only report template in the
   Object Template, state clearly that deleting it will delete all data owned
   by that object type, including its instances, properties/facts, identifiers
   and links. Require an explicit final confirmation for this full cascade.
5. **Apply one atomic cascade.** After validation and confirmation, delete the
   source-owned Strong Identifier values, facts and associations. Delete an
   instance only when no surviving template/source supports it and no external
   relationship references it. When deleting the last template, remove all
   instance data owned by the object type as stated in the warning. Enforce
   ownership with foreign keys; use restrictive references for cross-object
   links that cannot safely cascade.
6. **Commit or roll back.** Perform validation and deletion in one database
   transaction. On any conflict or database failure, roll back the entire
   operation; leave configuration and data unchanged and show the failure.
7. **Audit the decision.** Record actor, time, target template/version,
   validation result and affected row counts. The audit record explains the
   deletion; it must not keep the deleted identifier active or restore it as
   an archived matching key.

## Required invariants

- An object instance's UUID is unique, immutable and independent of source
  Strong Identifiers.
- Every object property, source fact, identifier value and object relationship
  references a valid UUID through a foreign key.
- Each active Strong Identifier value resolves to no more than one canonical
  object within its documented uniqueness scope. The uniqueness scope must be
  defined per identifier type before adding constraints.
- No active Strong Identifier binding points to a removed template or absent
  source field.
- Detaching or deleting an identifier cannot silently change an object's UUID
  or leave an object relationship dangling.
- Template deletion has no database effects before preview, binding validation
  and the required user confirmation succeed.
- A multi-template deletion only removes data owned by the selected source;
  objects still supported by another source survive. Orphan candidates are
  explicitly identified and handled by the confirmed cascade policy.
- Deleting the sole template requires a clear full-object-data warning and an
  explicit confirmation, then removes all data owned by that Object Template.
- Any failed validation or cascade leaves the database unchanged.

## First implementation slice

Use the user-defined Employee object type and one report template as the first
concrete instance of a generic object model:

1. Treat the Object Template as the Employee object-type definition, not one
   employee. Retain `engine_v2_objects.object_id` as the instance UUID and add
   engine-owned physical property, Strong Identifier and source-fact tables
   that reference it. Keep legacy Employee tables untouched.
2. Decide and implement the per-object-type schema strategy: versioned physical
   migrations or shared typed property storage with a governed field catalog.
   Schema changes happen per template version, not per object instance.
3. Add only the migrations required for missing object/property/identifier
   tables and source ownership metadata.
4. Implement attach/detach validation and preview for one Strong Identifier.
5. Exercise deleting one of two source templates, deleting the only template,
   blocked deletion with an attached identifier, blocked deletion with a live
   cross-object link, and transaction rollback.

Production file processing remains disabled until this contract and the import
readiness criteria are implemented and verified. See
[`2026-09-30_IMPORT_READINESS_AND_PLAN.md`](2026-09-30_IMPORT_READINESS_AND_PLAN.md).
