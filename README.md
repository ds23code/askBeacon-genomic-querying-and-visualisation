# Genomic AI Agents

Agent-based framework for querying genomic data in plain English.

**CSIRO · Dhruv Sharma · April 2026**

---

## What It Does

Type a question in plain English. The system selects the right AI agents, fetches real genomic data, and returns clean results – including tables, plots, and summary text.

**Example queries:**
```
"Find variants on chromosome 2 between 1.5M and 1.501M and plot allele frequencies"
"Get male individuals with regional failure"
"How many Europeans have breast cancer?"
```

The system automatically:
- Decides which agents to run (VCF, Beacon, Joiner, Executor)
- Fetches variant data from the 1000 Genomes Project
- Builds a Beacon v2 query with official ontology codes
- Merges results and generates visualisations

---

## Quick Start

### 1. Setup (once)

```bash
# Create a virtual environment
python3.12 -m venv venv312
source venv312/bin/activate   # or `venv312\Scripts\activate` on Windows

# Install Python dependencies
pip install -r requirements.txt
pip install streamlit          # optional, for the web UI

# Install bcftools (required for VCF queries)
brew install bcftools          # macOS
# sudo apt install bcftools    # Ubuntu/Debian

# Start Ollama (keep this terminal running)
ollama pull llama3
ollama serve

# Build the FAISS ontology index
python ontology/build_vector_db.py
```

### 2. Run the system

**Web UI (recommended):**
```bash
streamlit run app.py
```
Then open http://localhost:8501 in your browser.

**Command line:**
```bash
# Run individual agents
python main.py -a vcf -q "Get variants on chromosome 2 from 5.5M to 5.51M"
python main.py -a beacon -q "Find male individuals with regional failure"
python main.py -a join
python main.py -a execute -q "Plot allele frequencies as a bar chart" --csv-file outputs/joined.csv

# Run both VCF and Beacon together
python main.py -a both -q "Get variants on chromosome 5 for European males"
```

---

## Agent Overview

| Agent | Purpose |
|-------|---------|
| **VCF** | Fetches variant data from the 1000 Genomes Project using bcftools (ReAct loop) |
| **Beacon** | Builds a valid Beacon v2 JSON query from natural language |
| **Joiner** | Merges VCF output and Beacon query into a unified table |
| **Executor** | Generates and runs matplotlib code to create plots from the data |

The **orchestrator** automatically selects which agents to run based on your query. You can also override manually.

---

## File Structure

```
genomic-agents/
├── app.py                      # Streamlit web UI
├── orchestrator.py             # Automatically plans and runs agents
├── memory.py                   # JSON-based query history
├── main.py                     # CLI entry point
├── requirements.txt
├── config/
│   └── settings.py             # All configuration
├── templates/
│   └── bcftools_template.md    # 7 allowed bcftools command patterns
├── ontology/
│   ├── build_vector_db.py      # Builds FAISS index (run once)
│   ├── ontology_lookup.py      # Term → ontology code
│   ├── ontology.index          # FAISS binary index (generated)
│   └── ontology_meta.json      # Term codes and labels
├── agents/
│   ├── vcf_agent.py
│   ├── beacon_agent.py
│   ├── joiner_agent.py
│   └── executor_agent.py
├── tools/                      # Legacy wrappers (kept for reference)
└── outputs/                    # All results saved here
```

---

## Configuration

All settings are in `config/settings.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `"llama3"` | LLM model (must be pulled) |
| `OLLAMA_BASE_URL` | `"http://localhost:11434"` | Ollama server URL |
| `BEACON_BASE_URL` | `"https://beacon.demo.umccr.org"` | sBeacon endpoint |
| `ONTOLOGY_STRATEGY` | `"faiss"` | `"faiss"` (vector search) or `"vectorless"` (prompt-based) |
| `DEFAULT_VCF_FILE` | chr1 S3 URL | Fallback VCF file |

---

## Security & Privacy

- **LLM never sees raw genomic data**: VCF agent only passes file headers (metadata) to Ollama.
- **All processing is local**: Ollama runs on your machine; no cloud API calls.
- **Commands are validated**: Only bcftools commands allowed; forbidden tokens (`;`, `&&`, `rm`, etc.) are blocked.
- **Executor code is sandboxed**: Generated Python is checked for dangerous patterns before execution.

---

## Verification

To verify VCF output against UCSC Genome Browser:
1. Open any `.csv` in `outputs/` – note a `POS` value and `CHROM`.
2. Go to [genome.ucsc.edu](https://genome.ucsc.edu) and set assembly to **hg19 / GRCh37**.
3. Search: `chr2:5,500,000-5,510,000` (adjust chromosome and range).
4. Click the `Common dbSNP(155)` track – the REF/ALT should match.

---

## Next Steps

- Connect Beacon to a live production endpoint.
- Expand ontology using the full sBeacon `terms.csv`.
- Add session history display in Streamlit sidebar.

---

## License

This project is for research and educational purposes. See LICENSE file for details.