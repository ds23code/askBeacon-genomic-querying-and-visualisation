import streamlit as st
import pandas as pd
import json
from pathlib import Path

from orchestrator import run_workflow

# Page configuration
st.set_page_config(page_title="AskBeacon - Genomic Querying and Visualisation", layout="wide")

# Main title
st.title("AskBeacon – Genomic Querying and Visualisation")

# Sidebar for advanced options
with st.sidebar:
    st.header("Advanced Options")
    upload_vcf = st.file_uploader("Upload a VCF file (optional)", type=["vcf.gz", "vcf"])
    if upload_vcf:
        temp_vcf = Path("temp_upload.vcf.gz")
        with open(temp_vcf, "wb") as f:
            f.write(upload_vcf.read())
        st.success(f"Using uploaded file: {upload_vcf.name}")
    else:
        temp_vcf = None

    st.markdown("---")
    manual_agents = st.multiselect(
        "Select agents to run (empty = auto)",
        ["vcf", "beacon", "join", "execute"]
    )
    run_manually = st.checkbox("Manually override agents")

# Query input
user_query = st.text_area(
    "Enter your question:",
    height=100,
    placeholder="e.g., Find variants on chromosome 2 between 5.5M and 5.51M and plot allele frequencies"
)

# Run button
if st.button("Run", type="primary"):
    if not user_query.strip():
        st.warning("Please enter a question.")
        st.stop()

    with st.spinner("Planning and executing agents..."):
        try:
            if run_manually and manual_agents:
                result = run_workflow(user_query, verbose=False, actions_override=manual_agents)
            else:
                result = run_workflow(user_query, verbose=False)
        except Exception as e:
            st.error(f"Workflow error: {e}")
            st.stop()

    st.success("Workflow completed!")
    st.markdown("### Workflow Plan")
    st.write(f"**Actions executed:** {', '.join(result['actions'])}")

    # Expandable section for intermediate outputs
    with st.expander("Show intermediate outputs"):
        if "vcf_summary" in result:
            st.markdown("**VCF Command & Output**")
            st.code(result["vcf_summary"], language="text")
        if "beacon_result" in result:
            st.markdown("**Beacon Query**")
            st.json(result["beacon_result"])
        if "join_result" in result:
            st.markdown("**Join Summary**")
            st.write(result["join_result"].get("summary", ""))

    st.markdown("### Final Summary")
    st.write(result.get("final_summary", "No summary generated."))

    # Display generated files
    files = result.get("files", {})
    if files.get("vcf_csv") and Path(files["vcf_csv"]).exists():
        st.markdown("### VCF Data (first 10 rows)")
        df = pd.read_csv(files["vcf_csv"])
        st.dataframe(df.head(10))
        st.download_button(
            "Download VCF CSV",
            data=df.to_csv(index=False),
            file_name=Path(files["vcf_csv"]).name
        )

    if files.get("beacon_json") and Path(files["beacon_json"]).exists():
        st.markdown("### Beacon Query (from file)")
        with open(files["beacon_json"]) as f:
            content = f.read()
        st.text(content[:1000])  # preview

    if files.get("joined_csv") and Path(files["joined_csv"]).exists():
        st.markdown("### Joined Data (first 10 rows)")
        df_joined = pd.read_csv(files["joined_csv"])
        st.dataframe(df_joined.head(10))
        st.download_button(
            "Download Joined CSV",
            data=df_joined.to_csv(index=False),
            file_name=Path(files["joined_csv"]).name
        )

    # Show plot if available, otherwise show generated code (if any)
    plot_path = files.get("plot")
    plot_code = files.get("plot_code")
    if plot_path and Path(plot_path).exists():
        st.markdown("### Generated Plot")
        st.image(plot_path)
        if plot_code and Path(plot_code).exists():
            with open(plot_code, "r") as f:
                code = f.read()
            with st.expander("Show plot code"):
                st.code(code, language="python")
    elif plot_code and Path(plot_code).exists():
        st.markdown("### Plot Code (execution may have failed)")
        with open(plot_code, "r") as f:
            code = f.read()
        st.code(code, language="python")
        if "executor_result" in result:
            exec_res = result["executor_result"]
            if exec_res.get("success") is False:
                st.error(f"Execution failed with error:\n```\n{exec_res.get('error', 'No error captured')}\n```")
            if exec_res.get("output"):
                st.text(f"Output:\n{exec_res['output']}")
    else:
        st.info("No plot was generated.")