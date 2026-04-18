# pine/drawings/

Sample sketch JSONs for `tv drawings sketch`. Each file is a complete
spec — pipe one into the CLI to render the drawings on the active chart:

```bash
tv drawings sketch pine/drawings/sr_levels.json
tv drawings sketch pine/drawings/range_box.json

# Combine sketches:
tv drawings clear --name "S/R Levels"          # remove if present
tv drawings clear --name "Range box"

# Or generate from your own JSON / Python:
echo '{"name": "Quick line", "drawings": [{"type": "horizontal", "price": 27000, "color": "blue"}]}' \
    | tv drawings sketch --stdin
```

See [tv_automation/drawings.py](../../tv_automation/drawings.py) for the
full schema and supported drawing types.
