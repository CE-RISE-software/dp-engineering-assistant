# Reference Examples

The server can use CE-RISE examples as examples, then generalize from them.

The first curated reference example is the Digital Passport System Local Demonstrator. It is useful because it shows existing CE-RISE components working together locally, but its concrete products, payloads, local no-auth settings, storage choices, and ports are not defaults for adopters.

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
