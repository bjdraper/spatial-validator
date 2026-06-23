#!/usr/bin/env Rscript
# Fetch the DLPFC (Maynard et al. 2021) data via spatialLIBD and build
# per-section, per-layer fixtures for the agent eval.
#
#   Rscript data_prep/fetch_dlpfc.R
#
# Layer-as-cluster: each expert-annotated layer in a section becomes one test
# case, labelled with its top-N upregulated marker genes. Ground truth is the
# layer label. Output: data/fixtures/dlpfc/<section>.json
#
# First run installs spatialLIBD + scran + scuttle from Bioconductor and
# downloads the ~2 GB SpatialExperiment (cached by ExperimentHub afterwards).

options(timeout = 3600)  # the ExperimentHub download is large

TOP_N <- 15
SECTIONS <- c("151507", "151510", "151669", "151673", "151676")  # span 3 donors

# Resolve the repo root from this script's own path, so output lands in the
# right place regardless of the working directory.
args <- commandArgs(FALSE)
file_arg <- sub("^--file=", "", args[grepl("^--file=", args)])
repo <- normalizePath(file.path(dirname(file_arg), ".."))
OUT_DIR <- file.path(repo, "data", "fixtures", "dlpfc")

need <- c("spatialLIBD", "scran", "scuttle", "SpatialExperiment", "jsonlite")
miss <- need[!vapply(need, requireNamespace, logical(1), quietly = TRUE)]
if (length(miss)) {
  message("Installing missing packages: ", paste(miss, collapse = ", "))
  if (!requireNamespace("BiocManager", quietly = TRUE)) {
    install.packages("BiocManager", repos = "https://cloud.r-project.org")
  }
  BiocManager::install(miss, update = FALSE, ask = FALSE)
}

suppressPackageStartupMessages({
  library(spatialLIBD); library(scran); library(scuttle)
  library(SpatialExperiment); library(jsonlite)
})

message("Fetching DLPFC spe via spatialLIBD::fetch_data('spe') ...")
spe <- fetch_data(type = "spe")

# The manual-annotation column name has varied across releases — pick the first
# that exists.
cand <- c("layer_guess_reordered_short", "layer_guess_reordered",
          "layer_guess", "spatialLIBD")
layer_col <- cand[cand %in% colnames(colData(spe))][1]
if (is.na(layer_col)) {
  stop("No layer-annotation column found. colData columns: ",
       paste(colnames(colData(spe)), collapse = ", "))
}
message("Using layer column: ", layer_col)

symbols <- rowData(spe)$gene_name
if (is.null(symbols)) symbols <- rownames(spe)

dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

for (sid in SECTIONS) {
  sub <- spe[, spe$sample_id == sid]
  lab <- as.character(colData(sub)[[layer_col]])
  keep <- !is.na(lab) & !(lab %in% c("", "NA"))
  sub <- sub[, keep]; lab <- lab[keep]
  if (ncol(sub) == 0) { message("No spots for section ", sid, " — skipping"); next }

  sub <- logNormCounts(sub)
  mk <- findMarkers(sub, groups = lab, direction = "up", pval.type = "any")

  # Drop ubiquitous technical genes (mitochondrial, ribosomal, MALAT1/NEAT1) —
  # they dominate raw DE but carry no layer identity.
  noise <- "^(MT-|MTRNR|RP[SL][0-9]|MRP[SL]|MALAT1$|NEAT1$)"
  clusters <- lapply(names(mk), function(g) {
    tab <- mk[[g]]
    ord <- order(tab$Top)                       # rank all genes, then filter
    genes <- symbols[match(rownames(tab)[ord], rownames(sub))]
    genes <- genes[!is.na(genes) & genes != ""]
    genes <- unique(genes[!grepl(noise, genes)])
    list(cluster_id = g, ground_truth = g,
         top_genes = as.list(head(genes, TOP_N)), neighbors = list())
  })

  out <- list(dataset = "DLPFC (Maynard 2021)", section_id = sid, clusters = clusters)
  fn <- file.path(OUT_DIR, paste0(sid, ".json"))
  write_json(out, fn, auto_unbox = TRUE, pretty = TRUE)
  message("Wrote ", fn, " (", length(clusters), " layers)")
}

message("Done. Replace data/fixtures/dlpfc/sample.json usage by pointing the ",
        "eval at these real sections.")
