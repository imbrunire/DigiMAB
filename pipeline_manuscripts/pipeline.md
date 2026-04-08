# An Agent-Based Pipeline for the Semi-Automatic Processing of Archival Materials

## 1. Introduction

The digitization of cultural heritage materials has shifted from a focus on image acquisition to the broader challenge of **data structuring and semantic enrichment**. Archival documents, particularly manuscripts, present significant difficulties due to their heterogeneity, variability in script and language, and the presence of implicit or context-dependent information.

Fully automated approaches based on machine learning often struggle to achieve the level of accuracy required in archival contexts, while fully manual approaches are not scalable. This work proposes a **hybrid pipeline** that combines:

* deterministic extraction processes
* expert-generated metadata
* Large Language Models (LLMs) for interpretative tasks

The system is implemented as an **agentic architecture**, in which multiple agents interact through a shared memory, allowing for non-linear workflows and mutual validation of outputs.


## 2. General Architecture

The pipeline is structured as a sequence of interconnected stages, each contributing a specific layer of information. A key feature of the system is the **separation of metadata sources**, which reflects both epistemological and technical considerations.

Three distinct categories of metadata are identified:

1. **Technical metadata**, extracted automatically from image files
2. **Descriptive metadata**, manually curated by domain experts
3. **Derived metadata**, inferred through AI-based analysis

These layers are progressively integrated within a shared computational environment.


## 3. Technical Metadata Extraction

Technical metadata are extracted **externally to the agentic system** using EXIFTool. This design choice ensures that low-level file properties are obtained through a **deterministic and reproducible process**, independent of probabilistic models.

The extracted metadata include:

* file format and encoding
* image dimensions
* acquisition device
* cryptographic hash (MD5)

These data are subsequently injected into the system as part of the shared context. Their role is primarily structural and administrative, contributing to the completeness of the final METS record.


## 4. Manual Descriptive Metadata

A crucial component of the pipeline is the inclusion of **manually curated descriptive metadata**. These metadata are produced by domain experts and represent information that cannot be reliably inferred from the digital images alone.

Examples include:

* authorship and attribution
* date and place of creation
* material characteristics
* conservation state
* historical context

In the implementation, these metadata are initially recorded in a structured textual document and then programmatically converted into a JSON representation. Within the system, they are treated as **authoritative inputs**.

This principle is explicitly enforced in downstream processes. For instance, during transcription, manually provided metadata are considered **binding constraints**, and any discrepancy between visual evidence and metadata is resolved in favor of the latter.


## 5. Preprocessing of Visual Data

Before being processed by AI models, images undergo a series of transformations aimed at improving readability and reducing noise.

The preprocessing pipeline includes:

* conversion to grayscale
* contrast enhancement
* adaptive resizing to comply with API constraints
* encoding into Base64 format

As implemented in the system, preprocessing is dynamically adjusted to respect size limitations (e.g. maximum payload constraints in API calls), using iterative resizing and quality reduction strategies. 

This stage is essential for ensuring consistent input quality and optimizing model performance.


## 6. Shared Memory and Context Management

At the core of the architecture lies a **shared memory structure**, which enables communication between agents and supports stateful processing.

The memory model includes:

* external metadata (manual and technical)
* analytical outputs (with confidence scores)
* transcription results
* regesto output
* modification history

Each value stored in memory is associated with metadata, including:

* confidence score
* agent responsible for the update
* timestamp
* previous value (for versioning)

This design allows for **traceability, transparency, and iterative refinement**, which are essential in scholarly contexts. 


## 7. Agent-Based Processing

The system is composed of multiple agents, each responsible for a specific task. These agents operate over the shared memory and can both read and update its content.

### 7.1 Analysis Agent (Metadata Enrichment)

The Analysis Agent performs a visual and contextual analysis of the manuscript images. It integrates:

* the full set of images representing a single digital object
* the externally provided metadata

The agent extracts and infers:

* language
* document typology
* script type
* structural organization of the text
* presence of abbreviations and annotations

Each output is associated with a confidence score, allowing for subsequent validation or reprocessing.

The design explicitly considers the **document as a composite object**, rather than treating images independently. 


### 7.2 Transcription Agent

The Transcription Agent generates a **semi-diplomatic transcription** of the document.

A defining feature of this component is the explicit **hierarchy of sources**:

1. manually curated metadata (highest priority)
2. inferred metadata from the Analysis Agent
3. visual evidence from the images

This hierarchy is encoded directly in the prompting strategy. When discrepancies arise (e.g. between a signature in the image and the recorded author), the system enforces alignment with the manual metadata, while documenting the correction.

The transcription output is structured using XML-like tags, capturing:

* textual content
* marginalia
* abbreviations and their expansions
* semantic roles (e.g. sender, recipient, date)

Additionally, the agent reports:

* applied corrections
* detected contradictions
* areas of uncertainty

This approach transforms transcription into a **context-aware and self-validating process**.

### 7.3 Regesto Agent

The Regesto Agent produces a concise summary of the document, following archival conventions.

The regesto includes:

* identification of sender and recipient
* temporal information
* thematic description

The generation process relies on few-shot prompting and operates primarily on the transcription output. Despite its simplicity, this step provides a valuable abstraction layer for indexing and retrieval.

---

### 7.4 METS Formatting Agent

The final agent is responsible for generating a **METS XML document** compliant with the Eco-MIC profile.

This involves:

* integrating descriptive metadata (MODS)
* structuring administrative metadata
* encoding the logical and physical structure of the digital object

The correctness of this output is critical, as it determines interoperability with archival systems and validation APIs.


## 8. Discussion

The proposed pipeline demonstrates the advantages of combining:

* deterministic processes (EXIFTool)
* human expertise (manual metadata)
* probabilistic models (LLMs)

The agentic architecture introduces an additional layer of flexibility, enabling:

* iterative refinement
* cross-validation between tasks
* explicit handling of uncertainty

Moreover, the use of a shared memory model supports reproducibility and auditability, which are essential requirements in academic and archival contexts.


## 9. Conclusion

This work presents a structured approach to the semi-automatic processing of archival materials, addressing both technical and epistemological challenges. By integrating manual and automated processes within an agent-based framework, the pipeline achieves a balance between scalability and reliability.

Future developments may include:

* domain-specific model fine-tuning
* improved validation mechanisms for METS compliance
* integration into user-facing platforms

The approach outlined here contributes to ongoing efforts to bridge the gap between digitization and meaningful data production in cultural heritage contexts.
