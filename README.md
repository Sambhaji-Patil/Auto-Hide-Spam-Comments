# Spam Detection GitHub Action

A GitHub Action to detect and hide spam comments in discussions, issues, and pull requests automatically. This action uses a pre-trained machine learning model to classify and hide spam comments, helping to keep your repository clean.

## Features

- Detects and hides spam comments in discussions, issues, and pull requests.
- Easy to integrate into any repository with customizable inputs.
- Leverages GitHub API authentication for seamless access to repository content.

## Usage

To use this action in your repository, add the following to your workflow file (e.g., `.github/workflows/spam-detection.yml`).

### Example Workflow
```markdown
```yaml
name: Spam Detection Workflow

on:
  schedule:
    - cron: '0 * * * *'  # Runs the action every hour (you can customize this)

  issues:
    types: [opened, edited]
  pull_request:
    types: [opened, edited]
  discussion_comment:
    types: [created, edited]

jobs:
  spam-detection:
    runs-on: ubuntu-latest
    steps:
      - name: Run Spam Detection Action
        uses: Sambhaji-Patil/spam-detection-action@v1.5
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          repo_owner: 'your-github-username'
          repo_name: 'your-repo-name'
```

### Inputs

- **`github_token`** (required): The GitHub token used to authenticate API requests. Use `${{ secrets.GITHUB_TOKEN }}` for secure access to your repository.
- **`repo_owner`** (required): The username or organization name that owns the repository where the action will run.
- **`repo_name`** (required): The name of the repository where spam comments will be detected and hidden.

### Output

This action hides spam comments directly in the repository's issues, discussions, and pull requests. No additional output is generated.

## How It Works

The action leverages a machine learning model to classify comments as "spam" or "not spam" based on text content. If a comment is classified as spam, it will be automatically hidden in the relevant thread.

## Requirements

- **Python 3.8+** (bundled in the action environment)
- **GitHub Token** with `repo` permissions

## Development

To test the action locally or modify it:
1. Clone the repository.
2. Update the model or code as needed.
3. Use `act` to simulate GitHub Actions locally (recommended for testing).

```bash
act -j spam-detection
```
