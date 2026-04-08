# DigiMAB
Repository containing material related to DigiMAB - CNSL UniMC project on automatic extraction of metadata starting from different sources (handwritten, audios)

# 📜 Agentic Framework for Archival Processing (pipeline_manuscripts folder)

This repository implements an **agent-based framework** for the processing of archival materials, designed for cultural heritage and digital humanities workflows.

The system supports the semi-automatic creation of structured archival data, combining:

* automatic extraction of technical metadata
* manual curation of essential descriptive metadata
* AI-based enrichment, transcription, and summarization
* generation of METS-compliant XML files (Eco-MIC profile)

The approach prioritizes **accuracy, interoperability, and scalability**.

---

## 🧠 Conceptual Approach

The framework follows a **hybrid and agentic paradigm**.

Metadata creation is not fully automated. Instead, it is distributed across three layers:

* **Programmatic extraction** → technical metadata (external tools)
* **Human input** → critical descriptive metadata
* **AI agents** → enrichment, interpretation, and transformation

On top of this, the system adopts an **agentic architecture**, where multiple agents interact through a shared context rather than a strictly linear pipeline.

This allows:

* contextual reasoning across tasks
* cross-validation between outputs
* iterative refinement of metadata and transcription

---

## ⚙️ Architecture Overview

```text
                +----------------------+
                |     Input Data       |
                |----------------------|
                | - Manuscript images  |
                | - Manual metadata    |
                +----------+-----------+
                           |
                           v

        +----------------------------------------+
        |  External Technical Metadata Extraction|
        |----------------------------------------|
        | - EXIFTool                             |
        | - Format, size, device                 |
        | - MD5 hash                             |
        +------------------+---------------------+
                           |
                           v

        +----------------------------------------+
        | Manual Metadata Ingestion              |
        |----------------------------------------|
        | - Expert-curated metadata              |
        | - Parsed from structured documents     |
        | - Converted into JSON                  |
        +------------------+---------------------+
                           |
                           v

                +----------------------+
                |   Preprocessing      |
                |----------------------|
                | - Image enhancement  |
                | - Base64 encoding    |
                +----------+-----------+
                           |
                           v

        +-------------------------------------------+
        |        Shared Context / Memory            |
        |-------------------------------------------|
        | - Essential metadata (trusted)            |
        | - Technical metadata                     |
        | - AI-enriched metadata                   |
        +------------------+------------------------+
                           |
      -------------------------------------------------------
      |                         |                           |
      v                         v                           v

+----------------+     +----------------+        +----------------+
| Metadata Agent |     | Transcription  |        | Regesto Agent  |
|                |     | Agent          |        |                |
|----------------|     |----------------|        |----------------|
| Enrichment     |     | Diplomatic     |        | Archival       |
| & analysis     |     | transcription  |        | summary        |
|                |     | + XML tagging  |        | (≤ 50 words)   |
+--------+-------+     +--------+-------+        +--------+-------+
         |                      |                         |
         -------------------------------------------------
                           |
                           v

                +------------------------+
                | METS XML Generator     |
                |------------------------|
                | Eco-MIC compliant      |
                | structured output      |
                +------------------------+
```

---

## 🔄 Data Flow

The pipeline is structured as a sequence of **interdependent stages**, combining external tools, manual input, and AI agents.

### 1. Input

* Digital images representing a **single archival object** (multiple pages, front/back, attachments)
* Manually compiled metadata (e.g. Word document)

---

### 2. Technical Metadata Extraction (External)

Technical metadata is extracted **automatically outside the agentic system** using EXIFTool.

Extracted information includes:

* File format (JPEG, PNG, etc.)
* Image dimensions
* Acquisition device
* File hash (MD5)

This step ensures **reliable, reproducible, and tool-independent metadata acquisition**.

---

### 3. Manual Descriptive Metadata

Some metadata cannot be reliably inferred automatically and must be **provided by domain experts**.

Examples include:

* Author
* Date of creation
* Place of origin
* Material (e.g. paper, parchment)
* Conservation state
* Historical and archival notes

These metadata are:

* written in a structured document (e.g. Word file)
* parsed programmatically
* converted into JSON format

They serve as **trusted ground truth and contextual input** for the AI agents.

---

### 4. Preprocessing

* Image enhancement (grayscale conversion, contrast adjustment)
* Encoding images in Base64 for model input

---

### 5. Agentic Processing

The system orchestrates three main agents sharing a common context.

#### Metadata Agent

Enriches metadata by analyzing images and integrating existing data.

Extracts:

* Language
* Document type (letter, diary, register, etc.)
* Script type
* Layout structure (header, margins, notes)
* Presence of abbreviations, stamps, annotations

Each field includes a **confidence score**, enabling validation and potential reprocessing.

---

#### Transcription Agent

Produces a **diplomatic transcription** of the entire digital object.

Key features:

* Processes multiple images as a single logical unit
* Uses metadata context to improve recognition
* Outputs structured text with semantic tags

Example:

```xml
<transcription>
  <sender>...</sender>
  <recipient>...</recipient>
  <date>...</date>
  <authorialnotes>...</authorialnotes>
</transcription>
```

The agent can also:

* detect inconsistencies with metadata
* suggest corrections to the shared context

---

#### Regesto Agent

Generates a **concise archival summary**:

* Maximum 50 words
* Written in third person
* Includes key information:

  * sender and recipient
  * date
  * main content

This step remains effective even when transcription is partially uncertain.

---

### 6. METS XML Generation

The final output is a **METS XML file compliant with the Eco-MIC profile** that needs then to be validated on PostMan.

The system integrates:

* Descriptive metadata (MODS)
* Administrative metadata
* Structural metadata

Special attention is given to:

* mandatory fields
* structural consistency
* validation readiness

---




