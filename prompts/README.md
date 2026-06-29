# prompts/

This directory contains example prompt files that are evaluated by the CI pipeline
using PromptMatrix's rule-based eval engine.

## File Convention

- One prompt per `.txt` file
- Filename = prompt key (dots replace slashes for path safety)
- Example: `assistant.persona.txt` → key `assistant.persona`

## Running Evals Locally

```bash
# Register the prompt key in your local PromptMatrix instance first:
python pmx.py --url http://localhost:8000 register assistant.persona

# Then run rule-based eval:
python pmx.py --url http://localhost:8000 eval assistant.persona prompts/assistant.persona.txt --type rule_based
```

## CI Behavior

The `eval_prompts.yml` workflow automatically evaluates all `prompts/*.txt` files
on every push. The workflow requires two repository secrets to be set:

| Secret | Description |
|--------|-------------|
| `PM_URL` | URL of your PromptMatrix instance (e.g. `https://pm.yourorg.internal`) |
| `PM_TOKEN` | API token from your PromptMatrix workspace |

> **Note:** The workflow gracefully skips evaluation if no `.txt` files are found
> or if the secrets are not configured. This prevents false failures in forks
> and the public OSS repository.

## Adding Your Own Prompts

1. Create a `.txt` file in this directory
2. Write your prompt using `{{variable}}` syntax for runtime substitution
3. Push to `main` — CI will automatically score it with the rule-based engine
4. View results in the GitHub Actions log
