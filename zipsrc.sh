rm archive.zip
zip -r archive.zip . \
    -x "**.venv/**" -x "**.pio/**" -x "**.git/**" -x "**.obsidian/**" \
    -x "**.pytest_cache/**" -x "SilentWitness-Design-Docs/**" -x "_archive/**" \
    -x "captures**" -x "tools**" -x "docs**" -x "bringup**" -x "node_char**"




