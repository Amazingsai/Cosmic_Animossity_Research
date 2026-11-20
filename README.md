# Cosmic Animosity — LLM-Generated Enemy Behavior Trees

## Project Overview

Cosmic Animosity is an Unreal Engine 5.7 first-person shooter used as a research environment to investigate the feasibility of generating enemy behavior trees with large language models (LLMs).

This DS 340W research project uses GPT-4.1 to generate JSON representations of enemy behavior trees, validates the generated structures using Python, and evaluates selected behaviors in Unreal Engine against an existing baseline enemy AI.

The project investigates whether LLM-generated behavior trees can be validated, implemented, and executed successfully in gameplay.

## Research Questions

1. Can LLM-generated behavior trees satisfy structural, action, and logical validation requirements?
2. How do selected generated behavior trees perform in Unreal Engine compared with an existing baseline enemy AI?
3. What limitations are revealed when generated behavior trees are tested in gameplay?

## Software Requirements

For Python analysis:

- Windows 10 or 11
- Python 3
- Python dependencies required by the analysis scripts
- Git or a web browser for downloading the repository

For Unreal Engine gameplay:

- Unreal Engine 5.7
- A Windows computer capable of running the Unreal project

The Python analysis can be reproduced separately from Unreal Engine using the preserved experimental data.

## Downloading the Repository

1. Open the public repository:

   https://github.com/Amazingsai/Cosmic_Animossity

2. Select **Code → Download ZIP**.
3. Extract the ZIP to a local folder.
4. Open the extracted project folder in Visual Studio Code or PowerShell.

All commands below should be executed from the repository's root directory.

## Reproducing the Research Analysis

### Step 1: Verify Python

Open PowerShell and enter:

```powershell
python --version
```

Verify that Python is available.

### Step 2: Install Dependencies

Install the dependencies required by the repository's Python scripts.

If the repository includes a maintained `requirements.txt`, use:

```powershell
python -m pip install -r requirements.txt
```

### Step 3: Generate the Analysis Tables

Run:

```powershell
python scripts/build_analysis.py
```

This script processes the preserved validation and gameplay results and generates eight CSV analysis files in:

```text
results/analysis/
```

Expected damage cross-check:

```text
generated damage:
[180.0, 0.0, 175.0, 0.0, 0.0, 275.0]

baseline damage:
[335.0, 340.0, 320.0, 320.0, 330.0, 385.0]

totals generated=630.0 baseline=2030.0 (31.0 %)

zero-damage candidates:
[2, 6, 5] (3 of 6)
```

### Step 4: Generate Research Figures

Run:

```powershell
python scripts/make_figures.py
```

This generates seven SVG figures in:

```text
results/analysis/figures/
```

The figures visualize validation classifications, gameplay damage, action reachability, failure attribution, timing limitations, and the Candidate #5 rebuild investigation.

### Step 5: Verify the Results

The expected automated validation results for the 40 generated behavior trees are:

| Measurement | Result |
|---|---:|
| Generated outputs | 40 |
| JSON-readable outputs | 40 |
| Structurally valid outputs | 26 |
| Supported-action checks passed | 40 |
| VALID classification | 12 |
| REVIEW classification | 14 |
| INVALID classification | 14 |
| Outputs flagged for correction or review | 28 |

The expected gameplay results are:

| Candidate | Generated Damage | Baseline Damage |
|---|---:|---:|
| #1 | 180 | 335 |
| #2 | 0 | 340 |
| #3 | 175 | 320 |
| #6 | 0 | 320 |
| #5 | 0 | 330 |
| #4 | 275 | 385 |
| **Total** | **630** | **2030** |

Three of the six generated candidates successfully dealt damage during the original gameplay comparisons.

The generated AI dealt approximately 31% of the baseline's total damage. However, the baseline and generated enemies followed different attack-range and combat policies, so damage alone does not establish overall AI quality.

## Candidate #5 Rebuild Investigation

Candidate #5 originally dealt zero damage during the gameplay comparison.

A separate diagnostic investigation rebuilt its behavior tree using the same visible graph structure. The rebuilt tree successfully attacked and dealt approximately 15–25 damage per diagnostic phase.

This suggests an Unreal Engine asset-level discrepancy rather than a confirmed failure in the generated logic. The exact internal cause was not established.

These diagnostic results are stored separately in:

```text
results/analysis/phase7h_rebuild_diagnostics.csv
```

The rebuilt results are not included in the original gameplay damage totals.

## Unreal Engine Implementation

The Unreal Engine project contains the original enemy AI and the experimental behavior-tree implementation.

Important research components include:

- `BP_AICharacter`: Original baseline enemy AI
- `BP_BasicEnemyAI`: Experimental enemy character
- `AIController_ResearchEnemy`: Research AI controller
- `BB_EnemyBehavior`: Blackboard used for enemy decision-making
- `BTTask_EnemyAttack`: Custom enemy attack task
- Generated behavior-tree assets adapted for Unreal Engine

To open the Unreal project:

1. Install Unreal Engine 5.7.
2. Download and extract the repository.
3. Open the project's `.uproject` file.
4. Allow Unreal Engine to load and compile the required assets.
5. Open the appropriate gameplay level.
6. Use Play-in-Editor to inspect the enemy behavior.

The Python analysis scripts do not rerun Unreal gameplay experiments. They reproduce the analysis and visualizations from saved experimental results.

## Dataset

The research dataset contains 40 generated behavior trees from 10 prompt families.

The project includes saved generation outputs, validation results, and gameplay evaluation data.

The Week 11 dataset split uses:

| Dataset | Percentage | Outputs |
|---|---:|---:|
| Training | 70% | 28 |
| Test | 20% | 8 |
| Validation | 10% | 4 |

## Research Findings

The experiments produced three major findings:

1. GPT-4.1 successfully generated 40 JSON-readable behavior-tree outputs, but only 12 passed all automated validation checks.
2. Passing automated validation did not guarantee successful Unreal Engine execution. Some structurally valid trees still failed to perform their intended attacks.
3. Gameplay testing and implementation diagnostics revealed problems that could not be established through JSON validation alone.

The results support using automated validation as an initial screening stage, followed by actual gameplay testing before generated behavior trees are accepted for use.

## Limitations

The study used one LLM configuration, one Unreal Engine arena, and six purposively selected gameplay candidates. The player remained stationary during the main comparisons, and certain defensive or low-health behaviors were not fully exercised.

Consequently, the results should not be interpreted as general performance estimates for all LLM-generated enemy behavior trees.

## Future Work

Future research could compare multiple LLMs, fine-tune a model on behavior-tree examples, expand automated execution checks, and incorporate developer and player feedback during gameplay testing.

## Repository

https://github.com/Amazingsai/Cosmic_Animossity
