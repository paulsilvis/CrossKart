# CrossKart Telemetry

See CLAUDE.md for project overview.

## Quick start

```bash
# Install dependencies
pip install streamlit pandas numpy matplotlib

# Generate a test session
python3 tools/make_synth_session.py --out data/my_session.csv --track twisty --aggression 0.8 --seed 42 --validate

# Launch the viewer
streamlit run viewer/view_session.py
# then upload data/golden_twisty_seed42.csv (or any generated session)
```

## Directory layout

    tools/      make_synth_session.py   synthetic data generator
    viewer/     view_session.py         Streamlit replay viewer
    data/       *.csv                   session files
    docs/       session_format.md       CSV schema reference
    firmware/   (empty)                 ESP32 firmware — not yet started
