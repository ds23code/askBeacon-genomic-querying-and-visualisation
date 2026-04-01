# bcftools Command Templates
# ---------------------------
# The VCF agent picks ONE of these 7 templates and fills in the {{VARIABLES}}.
# This prevents the LLM from hallucinating flags or outdated syntax.
# All commands stream directly from S3 — nothing is downloaded to disk.
#
# CRITICAL: NEVER add -Oz, -o, --output or any output redirection flags.
# REGION FORMAT: use bare numbers — 2:5500000-5510000 NOT chr2:5500000-5510000
#           All output must go to stdout.

## Template 1 — Query a genomic region (most common)
## Use when: query mentions chromosome + position range
## IMPORTANT: region format is NUMBER:START-END — never use chr prefix
## Example: 2:5500000-5510000 (CORRECT) vs chr2:5500000-5510000 (WRONG)
bcftools view {{VCF_FILE}} --regions {{CHROM}}:{{START}}-{{END}}

## Template 2 — List all sample names
## Use when: query asks for sample names / individuals in the file
bcftools query -l {{VCF_FILE}}

## Template 3 — List chromosomes/contigs available in the file
## Use when: query asks what chromosomes are available
bcftools view -h {{VCF_FILE}} | grep "##contig"

## Template 4 — Filter by PASS only within a region
## Use when: query asks for high-quality / passing variants only
bcftools view {{VCF_FILE}} --apply-filters PASS --regions {{CHROM}}:{{START}}-{{END}}

## Template 5 — Filter by variant type (snps, indels, mnps, other)
## Use when: query asks specifically for SNPs, INDELs, or structural variants
bcftools view {{VCF_FILE}} --regions {{CHROM}}:{{START}}-{{END}} --type {{TYPE}}

## Template 6 — Extract specific INFO fields including population allele frequencies
## Use when: query asks for allele frequencies by population
bcftools query -f '%CHROM\t%POS\t%ID\t%REF\t%ALT\t%INFO/AF\t%INFO/EAS_AF\t%INFO/EUR_AF\t%INFO/AFR_AF\t%INFO/AMR_AF\t%INFO/SAS_AF\n' {{VCF_FILE}} --regions {{CHROM}}:{{START}}-{{END}}

## Template 7 — View file header only
## Use when: query asks about the file structure, format version, or reference genome
bcftools view -h {{VCF_FILE}}