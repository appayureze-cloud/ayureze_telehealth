---
title: "Phenotype microarray"
categories:
  - "Physiology"
date: 2016-11-30
---
# Phenotype microarray

[TOC]

The **phenotype microarray** approach is a technology for high-throughput phenotyping of cells. A phenotype microarray system enables one to monitor simultaneously the phenotypic reaction of cells to environmental challenges or exogenous compounds in a high-throughput manner. The phenotypic reactions are recorded as either end-point measurements or respiration kinetics similar to growth curves.

## Usages
High-throughput phenotypic testing is increasingly important for exploring the biology of bacteria, fungi, yeasts, and animal cell lines such as human cancer cells. Just as DNA microarrays and proteomic technologies have made it possible to assay the level of thousands of genes or proteins all a once, phenotype microarrays (PMs) make it possible to quantitatively measure thousands of cellular phenotypes all at once. The approach also offers potential for testing gene function and improving genome annotation. In contrast to the hitherto available molecular high-throughput technologies, phenotypic testing is processed with living cells, thus providing comprehensive information about the performance of entire cells. The major applications of the PM technology are in the fields of systems biology, microbial cell physiology and taxonomy, and mammalian cell physiology including clinical research such as on autism. Advantages of PMs over standard growth curves are that cellular respiration can be measured in environmental conditions where cellular replication (growth) may not be possible, and that respiration reactions are usually detected much earlier than cellular growth.

## Technology
A sole carbon source that can be transported into a cell and metabolized to produce NADH engenders a redox potential and flow of electrons to reduce a tetrazolium dye, such as tetrazolium violet, thereby producing purple color. The more rapid this metabolic flow, the more quickly purple color forms. The formation of purple color is a positive reaction. interpreted such that the sole carbon source is used as an energy source. A microplate reader and incubation facility is needed as a hardware device to provide the appropriate incubation conditions, and also automatically reads the intensity of colour formation during tetrazolium reduction in intervals of, e.g., 15 minutes.

The principal idea of retrieving information about the abilities of an organism and its special modes of action when making use of certain energy sources can be equivalently applied to other macro-nutrients such as nitrogen, sulfur or phosphorus and their compounds and derivatives. As an extension, the impact of auxotrophic supplements or antibiotics, heavy metals or other inhibitory compounds on the respiration behaviour of the cells can be determined.

## Data structure
In the case of positive reactions, the longitudinal kinetics are expected to appear as sigmoidal curves in analogy to typical bacterial growth curves. Comparable to bacterial growth curves, the respiration kinetic curves may provide valuable information coded in the length of the lag phase λ, the respiration rate μ (corresponding to the steepness of the slope), the maximum cell respiration A (corresponding to the maximum value recorded), and the area under the curve (AUC). In contrast to bacterial growth curves, there is typically no death phase in PMs, as the reduced tetrazolium dye is insoluble.

## Software
Proprietary and commercially available software is available that provides a solution for storage, retrieval, and analysis of high throughput phenotype data. A powerful free and open source software is the "opm" package based on R. "opm" contains tools for analyzing PM data including management, visualization and statistical analysis of PM data, covering curve-parameter estimation, dedicated and customizable plots, metadata management, statistical comparison with genome and pathway annotations, automatic generation of taxonomic reports, data discretization for phylogenetic software and export in the YAML markup language. In conjunction with other R packages it was used to apply boosting to re-analyse autism PM data and detect more determining factors. The "opm" package has been developed and is maintained at the Deutsche Sammlung von Mikroorganismen und Zellkulturen. Another free and open source software developed to analyze Phenotype Microarray data is "DuctApe", a Unix command-line tool that also correlates genomic data. Other software tools are PheMaDB, which provides a solution for storage, retrieval, and analysis of high throughput phenotype data, and the PMViewer software which focuses on graphical display but does not enable further statistical analysis. The latter is not publicly available.
