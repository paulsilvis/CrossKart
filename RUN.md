# CrossKart — Run Instructions

## One-time machine setup

### 1. Install direnv
```bash
brew install direnv
```

### 2. Hook direnv into your shell
Add one line to your shell config file, then restart your terminal.

**zsh** (default on modern macOS) — add to `~/.zshrc`:
```bash
eval "$(direnv hook zsh)"
```

**bash** — add to `~/.bashrc` or `~/.bash_profile`:
```bash
eval "$(direnv hook bash)"
```

### 3. Create the virtual environment
```bash
cd ~/CrossKart
python3 -m venv .venv
pip install streamlit pandas numpy matplotlib
```

### 4. Allow direnv to use the .envrc file
```bash
direnv allow
```

That's it. From now on the virtual environment activates automatically
whenever you enter ~/CrossKart (or any subdirectory), and deactivates
when you leave.

---

## Every subsequent session

```bash
cd ~/CrossKart          # venv activates automatically
```

No `source .venv/bin/activate` needed ever again.

---

## Generate a synthetic session

```bash
python3 tools/make_synth_session.py --out data/my_session.csv \
    --track twisty --aggression 0.8 --seed 42 --validate
```

Options:
    --track       oval | twisty | hill | mixed   (default: mixed)
    --aggression  0.0 to 1.0                     (default: 0.7)
    --seed        any integer                     (default: 1)
    --duration    seconds                         (default: 240)
    --validate    print physical plausibility report

The golden reference session is already in data/ and never needs regenerating:
    data/golden_twisty_seed42.csv

---

## Launch the viewer

```bash
streamlit run viewer/view_session.py
```

Opens at http://localhost:8501 in your browser.
Upload any CSV from the data/ directory, then hit Play.

Map mode options (optional CLI flag):
```bash
streamlit run viewer/view_session.py -- --map-mode grow
streamlit run viewer/view_session.py -- --map-mode local
streamlit run viewer/view_session.py -- --map-mode full    # default
```
