# Speeltuinen langs de snelweg

This Speeltuinen langs de snelweg is developed by David Haasnoot, though based heavily on other open source projects and is published under the GNU GPL-3 license.

## Configuring the template (remove before publishing)

### Naming

The current package name is `Speeltuinen_langs_snelweg` and `# Speeltuinen langs de snelweg`, if you search for this in your IDE (e.g. VS Code) you can replace these with your given name.

### Pre-commit

This repo has an example pre-commit configuration in `.pre-commit-config.yaml`.
Depending on your needs you might want to uncomment certain sections.
Let us know by making an issue if we missed a useful pre-commit.
Use `pre-commit install --hook-type pre-commit --hook-type pre-push` to automatically run pre-commit.

### GitHub Tests

In the folder `.github` there are four workflows which run automatically.
You will need to adjust these depending on your needs.

### Pixi

Read bellow for more information on pixi and a quick guideline you can include in your project.

## Getting started

### Using install (in future)

run `pip install Speeltuinen_langs_snelweg`

### developing with pixi

To manage the environment we use Pixi.

<details>
<summary>windows</summary>

```powershell
iwr -useb https://pixi.sh/install.ps1 | iex
```

</details>

<details>
<summary>Linux/Mac</summary>

```bash
curl -fsSL https://pixi.sh/install.sh | bash
```

</details>

#### installing

With the `Pixi` command in powershell install the python environment:

```bash
 cd ../Speeltuinen_langs_snelweg
 pixi install
```

The `pixi.lock` file loads the correct packages and downloads to the `.pixi` file, you can use this environment in developing and resting.
