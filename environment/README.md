# Environment

The release was validated with Python 3.13.5 and the exact versions in `requirements-lock.txt`.

For normal use:

```bash
python -m pip install -r environment/requirements.txt
```

For the closest recreation of the release validation environment:

```bash
python -m pip install -r environment/requirements-lock.txt
```

Brightway and ecoinvent are not required for the public TEA/custom-factor workflow.
