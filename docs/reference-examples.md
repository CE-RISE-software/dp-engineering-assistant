# Reference Examples

The server can use CE-RISE examples as examples, then generalize from them.

The first curated reference example is the Digital Passport System Local Demonstrator. It is useful because it shows existing CE-RISE components working together locally, but its concrete products, payloads, local no-auth settings, storage choices, and ports are not defaults for adopters.

Its three commands demonstrate different workflows:

| Command in the demonstrator repository | Workflow |
| --- | --- |
| `make demo` | Chair passport validation, persistence, read-back, and invalid-input rejection |
| `make demo-re-indicators` | All five published laptop RE indicators and invalid-input rejection |
| `make demo-see-impacts` | PV input validation, one calculation returning all 25 indicators, numerical comparison, and validation/persistence/read-back of the complete Integrated LCA output |

The separate `make validate-see-impacts` command checks readiness, input schemas, a saved output,
and invalid-input rejection. It does not run the calculation or persist records.

For another product, reuse the validation, calculation, comparison, and persistence sequence with
that product's foreground records and functional unit. SEE uses its released image's shared
background and methods; the PV example does not require an adopter to prepare a product-specific
Brightway project.

Use `generalize_reference_example` to extract reusable patterns such as:

- declaring the adopter's scope and value-chain roles;
- selecting required CE-RISE services and optional services;
- adapting the model registry catalog;
- preparing adopter-specific valid and invalid payloads;
- exercising the intended record lifecycle;
- turning demo checks into environment-appropriate operational checks.

The result separates:

- reusable pattern;
- contextualized action for the declared adoption context;
- CE-RISE assets to reuse;
- assumptions from the example that should not be carried over.

This keeps the demonstrator useful without making it a hidden architecture mandate.
