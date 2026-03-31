---
name: documentation-standards
description: Use this skill when writing documentation, generating docs, adding docstrings, creating READMEs, or documenting APIs. Activates when the user asks to document, add docs, write a README, or explain code for future developers.
version: 1.0.0
---

# Documentation Standards

You are writing documentation. Good documentation answers the questions someone will actually have — not every question they could theoretically have.

## What to Document

### Always Document
- **Public APIs** — Every public function, class, and endpoint. What it does, its parameters, return values, and error conditions.
- **Why, not what** — The code shows *what* happens. Comments and docs explain *why* it happens that way.
- **Non-obvious behavior** — Side effects, ordering requirements, thread safety, performance characteristics.
- **Configuration** — Environment variables, config files, feature flags. Include defaults and valid values.
- **Architecture decisions** — Why this approach was chosen, what trade-offs were made, what alternatives were rejected.

### Never Document
- **Obvious code** — `# increment counter` above `counter += 1` is noise.
- **Implementation details that will change** — Don't document internal algorithms unless they're critical to understand.
- **History** — That's what git blame is for. Don't add "Added by X on Y for Z" comments.

## Documentation Formats

### Python Docstrings
```python
def process_payment(amount: Decimal, currency: str, idempotency_key: str) -> PaymentResult:
    """Process a payment and return the result.

    Charges the customer's default payment method. If a payment with the same
    idempotency_key was already processed, returns the original result without
    charging again.

    Args:
        amount: Payment amount in the smallest currency unit (e.g., cents).
        currency: ISO 4217 currency code (e.g., "usd").
        idempotency_key: Unique key to prevent duplicate charges.

    Returns:
        PaymentResult with status and transaction ID.

    Raises:
        InsufficientFundsError: If the payment method has insufficient funds.
        InvalidCurrencyError: If the currency code is not supported.
    """
```

Use Google-style docstrings. Include Args, Returns, and Raises only when they're not obvious from the type hints.

### TypeScript / JavaScript
```typescript
/**
 * Process a payment and return the result.
 *
 * Charges the customer's default payment method. Idempotent — duplicate
 * calls with the same key return the original result.
 *
 * @throws {InsufficientFundsError} If payment method has insufficient funds
 */
async function processPayment(
  amount: number,
  currency: string,
  idempotencyKey: string,
): Promise<PaymentResult> {
```

Use JSDoc for public APIs. Skip `@param` and `@returns` when types are self-documenting.

### API Endpoints
```
## POST /api/payments

Process a payment.

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| amount | integer | yes | Amount in smallest currency unit |
| currency | string | yes | ISO 4217 currency code |
| idempotency_key | string | yes | Unique key for idempotent requests |

**Response (200):**
```json
{
  "id": "pay_abc123",
  "status": "succeeded",
  "amount": 1000,
  "currency": "usd"
}
```

**Errors:**
| Status | Code | Description |
|--------|------|-------------|
| 400 | invalid_currency | Currency code not supported |
| 402 | insufficient_funds | Payment method declined |
| 409 | duplicate_request | Idempotency key already used |
```

### README Sections
For project READMEs, include in this order:
1. **What it is** — One paragraph, no buzzwords
2. **Quick start** — Fewest steps to get running
3. **Configuration** — Environment variables and options
4. **Architecture** — High-level structure (only if non-obvious)
5. **Development** — How to run tests, lint, build
6. **Deployment** — How to ship it

### Inline Comments
```python
# Good: explains WHY
# Use exponential backoff because the payment API rate-limits
# at 100 req/s and returns 429s in bursts.
delay = BASE_DELAY * (2 ** attempt)

# Bad: explains WHAT (the code already says this)
# Multiply base delay by 2 to the power of attempt
delay = BASE_DELAY * (2 ** attempt)
```

## Tone & Style

- **Be direct.** "This function processes payments" not "This function is responsible for the processing of payment transactions."
- **Use active voice.** "Returns the user" not "The user is returned."
- **Write for the reader, not yourself.** Assume they're competent but unfamiliar with this specific code.
- **Include examples.** A single working example is worth a page of description.
- **Keep it current.** Wrong documentation is worse than no documentation. If you see stale docs while working, update or remove them.

## Rules

- Don't add docstrings to every function. Add them to public APIs, complex logic, and non-obvious behavior.
- Don't describe parameters whose names and types are self-explanatory.
- Don't write documentation that just restates the function signature in prose.
- DO include error conditions and edge cases — these are the most valuable docs.
- DO include examples for anything non-trivial.
- DO write the docs you wish existed when you first looked at this code.
