import json
import base64
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import os
from io import BytesIO

try:
    from PIL import Image, ImageEnhance
except ImportError:
    raise ImportError("Installa Pillow: pip install Pillow")


class AgentType(Enum):
    """Tipi di agenti nel sistema"""
    ANALYSIS = "agente_analisi"
    TRANSCRIPTION = "agente_trascrizione"
    REGESTO = "agente_regesto"
    METS_FORMATTER = "agente_mets_formatter" 
    

@dataclass
class ContextValue:
    """Rappresenta un valore nel contesto con metadati"""
    valore: Any
    confidence: float
    modificato_da: str
    timestamp: str
    versione_precedente: Optional[Any] = None

    def to_dict(self):
        return asdict(self)


class SharedMemory:
    """Memoria condivisa accessibile da tutti gli agenti"""


    def __init__(self):
        self.metadati_esterni: Dict = {}
        self.analisi: Dict[str, ContextValue] = {}
        self.trascrizione: Optional[str] = None
        self.regesto: Optional[str] = None 
        self.metadati_tecnici_immagini: Optional[Dict] = None  
        self.storia_modifiche: List[Dict] = []
        self.immagini_paths: List[str] = []

    def set_metadati_esterni(self, metadati: Dict):
        """Carica i metadati esterni dal file"""
        self.metadati_esterni = metadati
        self._log_modifica("sistema", "caricamento_metadati_esterni", metadati)

    def set_immagini(self, immagini_paths: List[str]):
        """Registra i path delle immagini dell'oggetto digitale"""
        self.immagini_paths = immagini_paths
        self._log_modifica("sistema", "registrazione_immagini", 
                          {"numero_immagini": len(immagini_paths)})

    def write(self, chiave: str, valore: Any, confidence: float,
              agente: AgentType, note: Optional[str] = None):
        """Scrive o aggiorna un valore nella memoria"""
        versione_precedente = None
        if chiave in self.analisi:
            versione_precedente = self.analisi[chiave].valore

        context_value = ContextValue(
            valore=valore,
            confidence=confidence,
            modificato_da=agente.value,
            timestamp=datetime.now().isoformat(),
            versione_precedente=versione_precedente
        )

        self.analisi[chiave] = context_value

        self._log_modifica(
            agente.value,
            f"aggiornamento_{chiave}",
            {
                "valore_nuovo": valore,
                "valore_precedente": versione_precedente,
                "confidence": confidence,
                "note": note
            }
        )

    def read(self, chiave: str) -> Optional[ContextValue]:
        """Legge un valore dalla memoria"""
        return self.analisi.get(chiave)

    def get_all_context(self) -> Dict:
        """Restituisce tutto il contesto corrente"""
        return {
            "metadati_esterni": self.metadati_esterni,
            "analisi": {k: v.to_dict() for k, v in self.analisi.items()},
            "trascrizione": self.trascrizione,
            "immagini_paths": self.immagini_paths
        }

    def _log_modifica(self, agente: str, azione: str, dettagli: Any):
        """Registra una modifica nella storia"""
        self.storia_modifiche.append({
            "timestamp": datetime.now().isoformat(),
            "agente": agente,
            "azione": azione,
            "dettagli": dettagli
        })

    def get_storia(self) -> List[Dict]:
        """Restituisce la storia completa delle modifiche"""
        return self.storia_modifiche


class LLMClient:
    """Client per interagire con API di LLM con Prompt Caching"""

    def __init__(self, provider: str = "anthropic", api_key: Optional[str] = None,
                 use_prompt_caching: bool = True):
        """
        Inizializza il client LLM

        Args:
            provider: "anthropic" per Claude
            api_key: Chiave API (se None, cerca nelle variabili d'ambiente)
            use_prompt_caching: Se True, usa il prompt caching di Anthropic 
        """
        self.provider = provider
        self.use_prompt_caching = use_prompt_caching

        if provider == "anthropic":
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=api_key)
                self.model = "claude-sonnet-4-5-20250929"
            except ImportError:
                raise ImportError("Installa: pip install anthropic")
        else:
            raise ValueError(f"Provider non supportato: {provider}")
        
        self.calls_count = 0
        
        if use_prompt_caching:
            print("\n💰 PROMPT CACHING ATTIVO")

    def _preprocess_image(self, image_path: str, contrast_factor: float = 2.0,
                         save_preview: bool = False, preview_folder: str = "./preview",
                         max_size_mb: float = 5.0) -> bytes:
        """Preprocessa l'immagine: conversione in bianco e nero, aumento contrasto e resize se necessario"""
        img = Image.open(image_path)
        
        # Conversione in bianco e nero
        img_bw = img.convert('L')
        
        # Aumento contrasto
        enhancer = ImageEnhance.Contrast(img_bw)
        img_enhanced = enhancer.enhance(contrast_factor)
        
        # Funzione helper per ottenere la dimensione effettiva in bytes del base64
        def get_size_bytes(image, quality=95):
            buffer = BytesIO()
            image.save(buffer, format='JPEG', quality=quality)
            jpeg_bytes = buffer.getvalue()
            # Calcola dimensione base64 (circa 1.37x la dimensione originale)
            base64_size = len(base64.standard_b64encode(jpeg_bytes))
            buffer.close()
            return base64_size, len(jpeg_bytes)
        
        # Limite in bytes (lasciamo margine di sicurezza: 4.8MB invece di 5MB)
        max_size_bytes = int(max_size_mb * 1024 * 1024 * 0.96)
        
        # Resize iterativo se l'immagine supera max_size_mb
        quality = 95
        current_img = img_enhanced
        base64_size, jpeg_size = get_size_bytes(current_img, quality)
        
        if base64_size > max_size_bytes:
            print(f"[RESIZE] Immagine {Path(image_path).name}: {base64_size/(1024*1024):.2f}MB > {max_size_mb}MB")
            
            # Strategia combinata: riduci dimensioni E qualità in modo più aggressivo
            scale_factor = 0.9
            
            # Prima riduci le dimensioni progressivamente
            while base64_size > max_size_bytes and scale_factor > 0.3:
                new_width = int(img_enhanced.width * scale_factor)
                new_height = int(img_enhanced.height * scale_factor)
                current_img = img_enhanced.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Riduci anche la qualità se necessario
                quality = 90 if scale_factor > 0.7 else 85 if scale_factor > 0.5 else 75
                
                base64_size, jpeg_size = get_size_bytes(current_img, quality)
                
                if base64_size > max_size_bytes:
                    scale_factor -= 0.05
            
            # Se ancora troppo grande, riduci ulteriormente la qualità
            while base64_size > max_size_bytes and quality > 60:
                quality -= 5
                base64_size, jpeg_size = get_size_bytes(current_img, quality)
            
            print(f"[RESIZE] Ridotta a: {base64_size/(1024*1024):.2f}MB (qualità: {quality}, scala: {scale_factor:.1%})")
            print(f"[RESIZE] Dimensioni: {current_img.width}x{current_img.height} (originale: {img_enhanced.width}x{img_enhanced.height})")
        
        # Salva preview se richiesto
        if save_preview:
            preview_path = Path(preview_folder)
            preview_path.mkdir(exist_ok=True)
            original_name = Path(image_path).stem
            preview_file = preview_path / f"{original_name}_preprocessed.jpg"
            current_img.save(preview_file, format='JPEG', quality=quality)
            print(f"[PREVIEW] Salvata in: {preview_file}")
        
        # Salva nel buffer finale
        buffer = BytesIO()
        current_img.save(buffer, format='JPEG', quality=quality)
        buffer.seek(0)
        return buffer.read()

    def _load_image_base64(self, image_path: str, preprocess: bool = True, 
                          contrast_factor: float = 2.0, save_preview: bool = False,
                          preview_folder: str = "./preview") -> tuple[str, str]:
        """Carica un'immagine, la preprocessa e la converte in base64"""
        if preprocess:
            image_bytes = self._preprocess_image(image_path, contrast_factor, 
                                                 save_preview, preview_folder)
            media_type = 'image/jpeg'
            image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
        else:
            path = Path(image_path)
            ext = path.suffix.lower()
            media_types = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }
            media_type = media_types.get(ext, 'image/jpeg')
            
            with open(image_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        return media_type, image_data

    def call_vision_api(self, prompt: str, image_paths: List[str],
                       system_prompt: str,
                       response_format: str = "json", 
                       preprocess_images: bool = True,
                       contrast_factor: float = 2.0,
                       save_preview: bool = False,
                       preview_folder: str = "./preview") -> Dict:
        """
        Chiama l'API vision con PROMPT CACHING

        Args:
            prompt: Il prompt testuale specifico dell'agente
            image_paths: Lista di path alle immagini del manoscritto
            system_prompt: System prompt (verrà cachato con cache_control)
            response_format: "json" o "text"
            preprocess_images: Se True, converte in B&W e aumenta contrasto
            contrast_factor: Fattore di aumento contrasto (default 2.0)
            save_preview: Se True, salva preview delle immagini preprocessate
            preview_folder: Cartella dove salvare le preview
        """
        if self.provider == "anthropic":
            return self._call_anthropic_vision(
                prompt, image_paths, system_prompt, response_format,
                preprocess_images, contrast_factor,
                save_preview, preview_folder
            )

    def call_text_api(self, prompt: str, system_prompt: str, 
                     response_format: str = "json") -> Dict:
        """Chiama l'API solo testo (per il regesto e METS)"""
        if self.provider == "anthropic":
            return self._call_anthropic_text(prompt, system_prompt, response_format)

    def _call_anthropic_vision(self, prompt: str, image_paths: List[str],
                               system_prompt: str, response_format: str, 
                               preprocess_images: bool = True,
                               contrast_factor: float = 2.0, 
                               save_preview: bool = False,
                               preview_folder: str = "./preview") -> Dict:
        """Chiamata specifica per Claude con PROMPT CACHING"""
        self.calls_count += 1
        
        print(f"\n[API CALL #{self.calls_count}] Chiamata vision API")
        print(f"[LLM] Preprocessing: {'ATTIVO' if preprocess_images else 'DISATTIVO'}")
        if preprocess_images:
            print(f"[LLM] Contrasto: {contrast_factor}x")
        if self.use_prompt_caching:
            print(f"[LLM] 💾 Prompt Caching: ATTIVO")
        
        # Costruisci content con tutte le immagini
        content = []
        
        # Aggiungi tutte le immagini
        for i, img_path in enumerate(image_paths):
            media_type, image_data = self._load_image_base64(
                img_path, 
                preprocess=preprocess_images,
                contrast_factor=contrast_factor,
                save_preview=save_preview,
                preview_folder=preview_folder
            )
            
            image_block = {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_data
                }
            }
            
            # CACHE_CONTROL: Aggiungi cache all'ULTIMA immagine
            if self.use_prompt_caching and i == len(image_paths) - 1:
                image_block["cache_control"] = {"type": "ephemeral"}
                print(f"[LLM] ✓ Cache abilitata per {len(image_paths)} immagini")
            
            content.append(image_block)
            print(f"[LLM] Immagine {i+1}/{len(image_paths)}: {Path(img_path).name}")
        
        # Aggiungi il prompt alla fine
        content.append({
            "type": "text",
            "text": prompt
        })

        # System prompt con cache_control
        system_blocks = [{
            "type": "text",
            "text": system_prompt
        }]
        
        # CACHE_CONTROL sul system prompt
        if self.use_prompt_caching:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}
            print(f"[LLM] ✓ Cache abilitata per system prompt")

        messages = [{
            "role": "user",
            "content": content
        }]

        # Chiamata API
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            temperature=0,
            system=system_blocks,
            messages=messages
        )

        content_text = response.content[0].text

        if response_format == "json":
            content_text = content_text.strip()
            if content_text.startswith("```json"):
                content_text = content_text[7:]
            if content_text.endswith("```"):
                content_text = content_text[:-3]
            return json.loads(content_text.strip())

        return {"text": content_text}

    def _call_anthropic_text(self, prompt: str, system_prompt: str, 
                            response_format: str) -> Dict:
        """Chiamata specifica per Claude solo testo con gestione migliorata degli errori"""
        self.calls_count += 1
        print(f"\n[API CALL #{self.calls_count}] Chiamata text API")
        
        messages = [{
            "role": "user",
            "content": prompt
        }]

        response = self.client.messages.create(
            model=self.model,
            max_tokens=16384,  # Aumentato per XML-METS più grandi
            temperature=0,
            system=system_prompt,
            messages=messages
        )

        content = response.content[0].text

        if response_format == "json":
            content = content.strip()
            # Rimuovi markdown code blocks
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # Tentativo di parsing con gestione errori migliorata
            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                print(f"[LLM] ⚠️ Errore parsing JSON: {e}")
                print(f"[LLM] Prime 500 caratteri della risposta: {content[:500]}")
                print(f"[LLM] Ultime 500 caratteri della risposta: {content[-500:]}")
                
                # Prova a salvare la risposta raw per debug
                try:
                    with open("debug_llm_response.txt", "w", encoding="utf-8") as f:
                        f.write(content)
                    print(f"[LLM] Risposta completa salvata in debug_llm_response.txt per debugging")
                except:
                    pass
                
                raise

        return {"text": content}
    

class AgentAnalysis:
    """Agente per l'analisi del manoscritto"""

    def __init__(self, memory: SharedMemory, llm_client: LLMClient):
        self.memory = memory
        self.llm = llm_client
        self.agent_type = AgentType.ANALYSIS

    def analyze(self) -> Dict:
        """Analizza il manoscritto ed estrae informazioni contestuali"""
        print(f"\n[{self.agent_type.value}] Inizio analisi del manoscritto...")
        
        immagini = self.memory.immagini_paths
        if not immagini:
            raise ValueError("Nessuna immagine registrata nella memoria")
        
        print(f"[{self.agent_type.value}] Analizzando {len(immagini)} immagini")

        metadati = self.memory.metadati_esterni

        # System prompt (verrà cachato!)
        system_prompt = """Sei un assistente specializzato nell'analisi e trascrizione di materiale archivistico manoscritto e/o stampato. Sei specializzato nell'analisi di materiale eterogeneo proveniente da diverse epoche storiche: lettere, quaderni, appunti, diari."""

        # User prompt specifico
        prompt = self._build_analysis_prompt(metadati, len(immagini))

        try:
            preprocess = True
            contrast = 2.0
            
            if hasattr(self, '_orchestrator_settings'):
                preprocess = self._orchestrator_settings.get('preprocess', True)
                contrast = self._orchestrator_settings.get('contrast', 2.0)
            
            response = self.llm.call_vision_api(
                prompt=prompt,
                image_paths=immagini,
                system_prompt=system_prompt,
                response_format="json",
                preprocess_images=preprocess,
                contrast_factor=contrast
            )

            print(f"[{self.agent_type.value}] Risposta LLM ricevuta")

            self._write_results_to_memory(response)

            return response

        except Exception as e:
            print(f"[{self.agent_type.value}] ❌ Errore durante l'analisi: {e}")
            raise

    def _build_analysis_prompt(self, metadati: Dict, num_immagini: int) -> str:
        """Costruisce il prompt per l'analisi"""
        base_prompt = f"""Sei un assistente specializzato nell'analisi e trascrizione di materiale archivistico manoscritto e/o stampato. Sei specializzato nell'analisi di materiale eterogeneo proveniente da diverse epoche storiche: lettere, quaderni, appunti, diari.

⚠️ IMPORTANTE: Stai analizzando {num_immagini} immagine/i che costituiscono UN UNICO OGGETTO DIGITALE.
Le immagini possono rappresentare:
- Più pagine dello stesso documento (es: pagina 1 e pagina 2 di una lettera)
- Fronte e retro di un foglio
- Documento principale + busta
- Documento principale + allegati

La tua analisi deve riferirsi all'INTERO oggetto digitale, considerando TUTTE le immagini nel loro insieme.

CONTESTO ESTERNO DISPONIBILE:
{json.dumps(metadati, indent=2, ensure_ascii=False)}

TASK: Analizza TUTTE le immagini e determina (per l'intero oggetto digitale):
1. **lingua**: La lingua principale del documento (es: latino, volgare toscano, italiano antico, latino medievale, etc.)
2. **tipologia_documento**: Il tipo di documento (es: lettera privata, diario, registro commerciale, atto notarile, etc.)
5. **abbreviazioni**: Lista di TUTTE le abbreviazioni trovate nelle varie immagini con relativo scioglimento. 
6. **aree_del_testo**: Aree del testo individuate in TUTTE le immagini (es: intestazione, note a margine, corpo del testo, busta, etc.)
7. **descrizione_elementi**: Note descrittive su elementi presenti in TUTTE le pagine/immagini (timbri, bolli, elementi di carta intestata, annotazioni archivistiche presenti). 
8. **particolarità_linguistiche**: Dizionario che come chiave possiede il termine / i termini sottolineati, barrati, o scritti in grassetto (da TUTTE le immagini) e come valore la tipologia di particolarità linguistica riscontrata.
9. **composizione_oggetto**: Descrizione di come le immagini si relazionano tra loro (es: "immagine 1: pagina 1 della lettera, immagine 2: pagina 2 della lettera", oppure "immagine 1: fronte, immagine 2: retro con indirizzo del destinatario")

Per ogni campo, fornisci anche un **confidence_score** tra 0 e 1.

FORMATO OUTPUT (JSON):
{{
  "lingua": {{
    "valore": "...",
    "confidence": 0.85,
    "note": "..."
  }},
  "tipologia_documento": {{
    "valore": "...",
    "confidence": 0.90,
    "note": "..."
  }},
  "natura_documento": {{
    "valore": "...",
    "confidence": 0.75,
    "note": "..."
  }},
  "tipo_scrittura": {{
    "valore": "...",
    "confidence": 0.75,
    "note": "..."
  }},
  "abbreviazioni": {{
    "valore": ["...", "..."],
    "confidence": 0.80,
    "note": "..."
  }},
  "aree_del_testo": {{
    "valore": ["...", "..."],
    "confidence": 0.85,
    "note": "..."
  }},
  "descrizione_elementi": {{
    "valore": ["...", "..."],
    "confidence": 0.85,
    "note": "..."
  }},
  "particolarità_linguistiche": {{
    "valore": {{"termine": "tipo_particolarità", ...}},
    "confidence": 0.85,
    "note": "..."
  }},
  "composizione_oggetto": {{
    "valore": "descrizione della relazione tra le immagini...",
    "confidence": 0.90,
    "note": "..."
  }}
}}

Rispondi SOLO con il JSON, senza altro testo."""

        return base_prompt

    def _write_results_to_memory(self, response: Dict):
        """Scrive i risultati dell'analisi nella memoria condivisa"""
        for chiave, dati in response.items():
            if chiave == "osservazioni":
                continue

            if isinstance(dati, dict) and "valore" in dati:
                self.memory.write(
                    chiave=chiave,
                    valore=dati["valore"],
                    confidence=dati.get("confidence", 0.5),
                    agente=self.agent_type,
                    note=dati.get("note")
                )

        print(f"[{self.agent_type.value}] Risultati scritti in memoria")


class AgentTranscription:
    """Agente per la trascrizione del manoscritto con validazione contro metadati esterni"""

    def __init__(self, memory: SharedMemory, llm_client: LLMClient):
        self.memory = memory
        self.llm = llm_client
        self.agent_type = AgentType.TRANSCRIPTION

    def transcribe(self) -> Dict:
        """Trascrive il manoscritto usando il contesto dalla memoria condivisa e validando contro metadati esterni"""
        print(f"\n[{self.agent_type.value}] Inizio trascrizione...")

        immagini = self.memory.immagini_paths
        if not immagini:
            raise ValueError("Nessuna immagine registrata nella memoria")
        
        print(f"[{self.agent_type.value}] Trascrivendo {len(immagini)} immagini")

        context = self.memory.get_all_context()

        print(f"[{self.agent_type.value}] Contesto utilizzato:")
        for k, v in context['analisi'].items():
            print(f"  - {k}: {v['valore']} (confidence: {v['confidence']:.2f})")
        
        # Stampa metadati esterni se presenti
        if context['metadati_esterni']:
            print(f"[{self.agent_type.value}] Metadati esterni (VINCOLANTI):")
            for k, v in context['metadati_esterni'].items():
                print(f"  - {k}: {v}")

        # System prompt (STESSO dell'analisi - verrà letto dalla cache!)
        system_prompt = """Sei un assistente specializzato nell'analisi e trascrizione di materiale archivistico manoscritto e/o stampato. 
        Sei specializzato nell'analisi di materiale eterogeneo proveniente da diverse epoche storiche: lettere, quaderni, appunti, diari."""

        prompt = self._build_transcription_prompt(context)

        try:
            preprocess = True
            contrast = 2.0
            save_preview = False
            preview_folder = "./preview"
            
            if hasattr(self, '_orchestrator_settings'):
                preprocess = self._orchestrator_settings.get('preprocess', True)
                contrast = self._orchestrator_settings.get('contrast', 2.0)
                save_preview = self._orchestrator_settings.get('save_preview', False)
                preview_folder = self._orchestrator_settings.get('preview_folder', './preview')
            
            # STESSE IMMAGINI dell'analisi - verranno lette dalla cache!
            response = self.llm.call_vision_api(
                prompt=prompt,
                image_paths=immagini,
                system_prompt=system_prompt,
                response_format="json",
                preprocess_images=preprocess,
                contrast_factor=contrast,
                save_preview=save_preview,
                preview_folder=preview_folder
            )

            print(f"[{self.agent_type.value}] Risposta LLM ricevuta")

            # Salva la trascrizione
            trascrizione = response.get("trascrizione", "")
            self.memory.trascrizione = trascrizione
            
            # Log eventuali correzioni applicate
            if response.get("correzioni_applicate"):
                print(f"[{self.agent_type.value}] ⚠️ Correzioni applicate basate su metadati esterni:")
                for correzione in response["correzioni_applicate"]:
                    print(f"  • {correzione}")

            print(f"[{self.agent_type.value}] Trascrizione completata")

            return {
                "stato": "completato",
                "trascrizione": trascrizione,
                "note_trascrittore": response.get("note", ""),
                "correzioni_applicate": response.get("correzioni_applicate", []),
                "contraddizioni_rilevate": response.get("contraddizioni_rilevate", [])
            }

        except Exception as e:
            print(f"[{self.agent_type.value}] ❌ Errore: {e}")
            raise

    def _build_transcription_prompt(self, context: Dict) -> str:
        """Costruisce il prompt per la trascrizione con validazione contro metadati esterni"""
        analisi = context['analisi']
        metadati_esterni = context['metadati_esterni']
        num_immagini = len(context['immagini_paths'])

        prompt = f"""Trascrivi accuratamente il testo di TUTTE le {num_immagini} immagini che costituiscono l'oggetto digitale.

⚠️ IMPORTANTE: Le immagini formano UN UNICO OGGETTO DIGITALE.
Devi fornire UNA TRASCRIZIONE UNIFICATA che consideri tutte le immagini nel loro ordine logico.

============================================================
GERARCHIA DELLE FONTI PER LA TRASCRIZIONE
============================================================

⚠️ REGOLA FONDAMENTALE - VALIDAZIONE CON METADATI ESTERNI:

I METADATI ESTERNI sono stati inseriti MANUALMENTE da archivisti professionisti.
Questi metadati hanno PRIORITÀ ASSOLUTA e sono VINCOLANTI per la trascrizione.

🔵 METADATI ESTERNI (fonte primaria - VINCOLANTI):
"""

        # Lista i metadati esterni disponibili
        if metadati_esterni:
            prompt += "\nI seguenti metadati DEVONO essere rispettati nella trascrizione:\n"
            for chiave, valore in metadati_esterni.items():
                prompt += f"  • {chiave}: {valore}\n"
            
            prompt += """
📋 REGOLE DI VALIDAZIONE OBBLIGATORIE:

1. **AUTORE/MITTENTE**:
   - Se presente nei metadati esterni → la firma nel documento DEVE corrispondere
   - Se trascrivendo la firma trovi un nome DIVERSO → CORREGGI usando i metadati esterni
   - Aggiungi una nota nel campo "correzioni_applicate"

2. **DATA**:
   - Se presente nei metadati esterni → la data nel documento DEVE corrispondere
   - Se trascrivendo la data trovi una data DIVERSA → CORREGGI usando i metadati esterni
   - IMPORTANTE: Potrebbero esserci variazioni di formato (es. "16 dicembre 1843" vs "16/12/1843")
     ma il giorno/mese/anno devono coincidere
   - Se la data è parzialmente illeggibile, usa i metadati esterni per completarla
   - Aggiungi una nota nel campo "correzioni_applicate"

3. **ALTRI CAMPI**:
   - Se altri campi sono presenti nei metadati esterni (es. luogo, destinatario)
     e sono visibili nel documento → devono essere coerenti
   - In caso di discrepanza → PREVALGONO i metadati esterni

⚠️ COME APPLICARE LE CORREZIONI:

Se devi correggere un elemento nella trascrizione basandoti sui metadati esterni:
- Trascrivi usando il valore dei METADATI ESTERNI
- Aggiungi un commento XML: <!-- CORRETTO da metadati esterni: visto "[testo_visto]", usato "[testo_corretto]" -->
- Registra la correzione nel campo "correzioni_applicate"

ESEMPIO:
Se vedi nella firma "pietro giordini" ma i metadati esterni dicono autore="Pietro Giordani":
<sender>Pietro Giordani<!-- CORRETTO da metadati esterni: visto "pietro giordini" --></sender>

Se vedi una data "15 dicembre" ma i metadati esterni dicono data="16 dicembre 1843":
<date>16 dicembre 1843<!-- CORRETTO da metadati esterni: visto "15 dicembre" --></date>

"""
        else:
            prompt += "\nNessun metadato esterno disponibile - trascrivi fedelmente ciò che vedi.\n"

        prompt += """
============================================================
CONTESTO PALEOGRAFICO E LINGUISTICO:
============================================================

"""
        prompt += json.dumps(analisi, indent=2, ensure_ascii=False) + "\n"

        if metadati_esterni:
            prompt += """
============================================================
METADATI ESTERNI (VINCOLANTI):
============================================================

"""
            prompt += json.dumps(metadati_esterni, indent=2, ensure_ascii=False) + "\n"

        prompt += """
============================================================
LINEE GUIDA PER LA TRASCRIZIONE:
============================================================

Analizza l'immagine nella sua completezza e identifica le diverse aree di testo. Poi segui queste linee guida:

**STRUTTURA E TAG:**
- Le annotazioni archivistiche a matita (es. 05.1063) devono essere trascritte e racchiuse all'interno di <archivaldescription>
- Le note autografe a margine del testo devono essere racchiuse all'interno di <marginalia>. Le note autografe potrebbero anche essere scritte ruotate di 90 gradi rispetto al corpo del testo.
- La trascrizione del testo deve essere racchiusa all'interno di <transcription>. Questo tag contiene l'intero testo autografo da TUTTE le immagini.
- Le parole sottolineate devono essere racchiuse all'interno del tag <s>
- Le parole barrate all'interno del tag <del>
- Le parole in grassetto all'interno del tag <b>
- Le abbreviazioni devono essere taggate all'interno del tag <choice>, dentro a questo tag utilizza <abbr> per contenere il testo dell'abbreviazione e <expan> contiene la versione estesa dell'abbreviazione.
- Se ci sono più pagine, mantieni la sequenza logica e indica chiaramente il passaggio da una pagina all'altra con <!-- Pagina N -->

**SE IL TESTO È UNA LETTERA:**
Devono essere inseriti dei tag che vanno ad identificare:
- Il mittente <sender> - generalmente è l'autore della lettera. La firma del mittente generalmente si trova in basso, alla fine della lettera
  ⚠️ SE presente nei metadati esterni come "autore" → DEVE corrispondere, altrimenti CORREGGI
- Il destinatario <recipient> - generalmente si trova all'inizio della lettera, oppure sulla busta/retro
- La data di stesura della lettera <date>
  ⚠️ SE presente nei metadati esterni come "data di creazione" → DEVE corrispondere, altrimenti CORREGGI
- Il luogo di spedizione <place_sender> - generalmente si trova all'inizio della lettera, vicino alla data
- Il luogo di arrivo <place_recipient> - generalmente questo dato è presente sulla busta o sul retro

Se uno di questi elementi non è presente nel documento che stai analizzando, non inserirlo. Non inventare contenuto.

**FEDELTÀ AL TESTO:**
1. La trascrizione deve essere semi-diplomatica. Mantieni massima fedeltà al testo originale
2. Se sono presenti errori di ortografia, non correggerli (TRANNE se contrastano con metadati esterni vincolanti)
3. Espandi le abbreviazioni standard del periodo tra parentesi quadre [espansione]
4. Segna passaggi illeggibili con [...]
5. Mantieni la punteggiatura originale dove possibile
6. Indica incertezze con (?) dopo la parola
7. Se ci sono più immagini/pagine, trascrivi tutto in sequenza mantenendo l'ordine logico

**VALIDAZIONE E CORREZIONE:**
Durante la trascrizione, confronta continuamente ciò che vedi con i metadati esterni.
Se trovi DISCREPANZE su elementi chiave (autore, data), applica la CORREZIONE come spiegato sopra.

============================================================
FORMATO OUTPUT (JSON):
============================================================

{
  "trascrizione": "Il testo trascritto completo da tutte le immagini con tag XML...",
  "note": "Eventuali osservazioni sulla trascrizione",
  "correzioni_applicate": [
    "Firma corretta da 'pietro giordini' a 'Pietro Giordani' (metadati esterni)",
    "Data corretta da '15 dicembre' a '16 dicembre 1843' (metadati esterni)"
  ],
  "contraddizioni_rilevate": [
    {
      "campo": "autore",
      "valore_metadati_esterni": "Pietro Giordani",
      "valore_visto_documento": "pietro giordini",
      "azione": "corretto_con_metadati_esterni",
      "confidence": 0.95
    }
  ],
  "aree_incerte": ["riga 3-5: scrittura sbiadita", "..."]
}

⚠️ IMPORTANTE:
- Se applichi correzioni basate su metadati esterni, compila "correzioni_applicate" E "contraddizioni_rilevate"
- Se non ci sono correzioni, lascia "correzioni_applicate" come array vuoto []
- Se non ci sono contraddizioni rispetto all'analisi paleografica, lascia "contraddizioni_rilevate" come array vuoto []

Rispondi SOLO con il JSON, senza altro testo."""

        return prompt

class AgentRegesto:
    """Agente per la creazione del regesto con gerarchia epistemica delle fonti"""
    
    def __init__(self, memory: SharedMemory, llm_client: LLMClient):
        self.memory = memory
        self.llm = llm_client
        self.agent_type = AgentType.REGESTO
    
    def crea_regesto(self) -> Dict:
        """
        Crea il regesto del documento basandosi su una gerarchia epistemica delle fonti
        
        Usa solo text API con gerarchia esplicita delle fonti per massima efficienza.
        Non usa vision API per ridurre i costi - si affida alla gerarchia epistemica.
        
        Returns:
            Dict con stato, regesto, note e fonti utilizzate
        """
        print(f"\n[{self.agent_type.value}] Inizio creazione regesto...")
        
        context = self.memory.get_all_context()
        
        if not context.get('trascrizione'):
            raise ValueError("Impossibile creare regesto: trascrizione non disponibile")
        
        # System prompt
        system_prompt = """Sei un archivista esperto nella creazione di regesti per documenti storici.
Hai accesso a multiple fonti di informazione con diversi livelli di affidabilità."""
        
        prompt = self._build_regesto_prompt_con_gerarchia(context)
        
        try:
            print(f"[{self.agent_type.value}] Creazione regesto con GERARCHIA EPISTEMICA (solo text)")
            
            response = self.llm.call_text_api(
                prompt=prompt,
                system_prompt=system_prompt,
                response_format="json"
            )
            
            regesto = response.get("regesto", "")
            
            print(f"[{self.agent_type.value}] Regesto creato ({len(regesto)} caratteri)")
            
            # Stampa le fonti utilizzate se presenti
            if "fonti_utilizzate" in response:
                print(f"[{self.agent_type.value}] Fonti utilizzate:")
                for campo, fonte in response["fonti_utilizzate"].items():
                    print(f"  • {campo}: {fonte}")
            
            self.memory._log_modifica(
                agente=self.agent_type.value,
                azione="creazione_regesto",
                dettagli={
                    "lunghezza": len(regesto),
                    "metodo": "gerarchia_epistemica",
                    "fonti_utilizzate": response.get("fonti_utilizzate", {})
                }
            )
            
            return {
                "stato": "completato",
                "regesto": regesto,
                "note": response.get("note", ""),
                "metodo": "gerarchia_epistemica",
                "fonti_utilizzate": response.get("fonti_utilizzate", {})
            }
            
        except Exception as e:
            print(f"[{self.agent_type.value}] ❌ Errore: {e}")
            raise
    
    def _build_regesto_prompt_con_gerarchia(self, context: Dict) -> str:
        """Costruisce il prompt con GERARCHIA EPISTEMICA ESPLICITA delle fonti"""
        
        prompt = """Sei un archivista esperto nella creazione di regesti per documenti storici.

⚠️ GERARCHIA DELLE FONTI (VINCOLANTE):

Le informazioni che ti fornisco hanno DIVERSI LIVELLI DI AFFIDABILITÀ.
Devi rispettare RIGOROSAMENTE questa gerarchia quando crei il regesto:

LIVELLO 1 - FONTI PRIMARIE (massima affidabilità):
   
   A) METADATI ESTERNI (inseriti manualmente da archivisti)
      → autore, data, luogo SE presenti
      → Provengono da inventari archivistici professionali
      → PRIORITÀ ASSOLUTA per questi campi
   
   B) ANALISI PALEOGRAFICA E DOCUMENTARIA (analisi specialistica)
      → tipologia_documento, composizione_oggetto, aree_del_testo, lingua
      → Provengono da analisi visiva specialistica del manoscritto
      → Include un punteggio di confidence (0-1)
      → Se confidence ≥ 0.75 → alta affidabilità
      → Se confidence < 0.6 → usa con cautela

LIVELLO 2 - FONTI DI SUPPORTO (potenzialmente rumorose):
   
   A) TAG XML NELLA TRASCRIZIONE (struttura affidabile)
      → <sender>, <recipient>, <date>, <place_sender>, <place_recipient>
      → Questi tag sono il risultato di una trascrizione strutturata
      → Più affidabili del testo libero ma meno dei metadati esterni
   
   B) TRASCRIZIONE TESTO LIBERO (può contenere errori)
      → Il testo continuo della trascrizione
      → Può contenere errori di riconoscimento del testo manoscritto
      → USA SOLO per comprendere il contenuto tematico
      → NON dedurre nomi, date o ruoli SOLO dal testo libero

REGOLE DI DECISIONE VINCOLANTI:

1. MITTENTE:
   1° Cerca in METADATI ESTERNI (campo "autore")
   2° Se assente, cerca tag XML <sender> nella TRASCRIZIONE
   3° Se assente, estrai con CAUTELA dal testo libero
   4° Se impossibile determinare con certezza, ometti o usa "autore sconosciuto"

2. DESTINATARIO:
   1° Cerca in METADATI ESTERNI (se presente)
   2° Se assente, cerca tag XML <recipient> nella TRASCRIZIONE
   3° Se assente, estrai con CAUTELA dal testo libero
   4° Se impossibile determinare con certezza, ometti

3. DATA:
   1° Cerca in METADATI ESTERNI (campo "data di creazione")
   2° Se assente, cerca tag XML <date> nella TRASCRIZIONE
   3° Se assente, estrai con CAUTELA dal testo libero
   4° Se impossibile determinare con certezza, ometti o usa "data incerta"

4. LUOGO:
   1° Cerca in METADATI ESTERNI (se presente)
   2° Se assente, cerca tag XML <place_sender> nella TRASCRIZIONE
   3° Se assente, estrai con CAUTELA dal testo libero
   4° Se impossibile determinare con certezza, ometti

5. TIPOLOGIA DOCUMENTO:
   → Usa ANALISI PALEOGRAFICA (campo "tipologia_documento")
   → Se confidence ≥ 0.75, usa con fiducia
   → Se confidence < 0.6, verifica coerenza con trascrizione

6. CONTENUTO/TEMA:
   → Usa la TRASCRIZIONE (è affidabile per il contenuto generale)
   → Sintetizza il messaggio principale
   → Identifica richieste, informazioni o riferimenti importanti

⚠️ IN CASO DI CONFLITTO TRA FONTI:
   La priorità è SEMPRE:
   1° METADATI ESTERNI
   2° ANALISI PALEOGRAFICA (se confidence ≥ 0.75)
   3° TAG XML TRASCRIZIONE
   4° TESTO LIBERO TRASCRIZIONE

⚠️ GESTIONE DELL'INCERTEZZA:
   - Se confidence < 0.6 → usa formulazioni caute ("probabilmente", "sembra")
   - Se informazione mancante in fonti primarie → preferisci omettere piuttosto che inventare
   - Se devi usare solo testo libero → segnala nelle note

Un REGESTO è una descrizione sintetica ma completa del contenuto di un documento, che include:
- Chi scrive a chi (mittente e destinatario)
- Quando è stato scritto
- Di cosa parla (tema principale)
- Eventuali richieste, informazioni importanti o riferimenti significativi

Il regesto deve essere:
- Chiaro, conciso e informativo
- Scritto in terza persona
- Massimo 100 parole
- Basato RIGOROSAMENTE sulla gerarchia delle fonti

============================================================
ESEMPI DI REGESTI CORRETTI:
============================================================

--- ESEMPIO 1 ---

METADATI ESTERNI (fonte primaria):
{
  "autore": "Pietro Giordani",
  "data di creazione": "16 dicembre 1843"
}

ANALISI PALEOGRAFICA (fonte primaria, con confidence):
{
  "tipologia_documento": {
    "valore": "lettera privata",
    "confidence": 0.92,
    "fonte": "agente_analisi"
  },
  "lingua": {
    "valore": "italiano",
    "confidence": 0.95,
    "fonte": "agente_analisi"
  },
  "composizione_oggetto": {
    "valore": "documento costituito da una singola pagina manoscritta",
    "confidence": 0.88,
    "fonte": "agente_analisi"
  }
}

TRASCRIZIONE (fonte secondaria):
<archivaldescription>05.1064</archivaldescription>

<transcription>
<date>Sabato 16. dicembre</date>

<recipient>Caro Signor Torelli</recipient>,

questa mia dovrà giungerle tardi: ma sappia che solamente ieri ho 
ricevuto la sua pregiatissima degli 11. Invano mi stimola VS: io sono un
povero vecchio, che da un pezzo non fa e non può fare la minima
cosa. Io m'aspetto (e desidero) ogni giorno il morire.
Le rendo mille grazie del suo giornale, che vo ricevendo. Io le deside-
ro di cuore ogni lunghezza e pienezza di prosperità: ella si assicuri
del mio buon volere; ma compatisca l'impossibilità.

<sender>Suo Affez.mo Servitore
pietro giordani.</sender>
</transcription>

REGESTO CORRETTO:
Pietro Giordani scrive al Signor Torelli il 16 dicembre 1843 per ringraziarlo della sua lettera dell'11. Si scusa per non poter fare di più a causa della sua età avanzata e delle sue condizioni di salute precarie. Ringrazia Torelli per l'invio del giornale e gli augura ogni prosperità.

ANALISI DELLE FONTI UTILIZZATE:
{
  "mittente": "metadati_esterni",
  "destinatario": "trascrizione_tag_xml",
  "data": "metadati_esterni",
  "luogo": "non_presente",
  "contenuto": "trascrizione_testo",
  "tipologia": "analisi_paleografica"
}

MOTIVAZIONE:
✓ Mittente: METADATI ESTERNI (campo "autore") - fonte primaria
✓ Data: METADATI ESTERNI (campo "data di creazione") - fonte primaria, validata da tag XML
✓ Destinatario: TAG XML <recipient> - fonte secondaria affidabile
✓ Contenuto: TRASCRIZIONE testo - uso appropriato per tema
✓ Tipologia: ANALISI PALEOGRAFICA - confidence 0.92 (alta affidabilità)

------------------------------------------------------------

--- ESEMPIO 2 ---

METADATI ESTERNI (fonte primaria):
{
  "autore": "Sibilla Aleramo",
  "data di creazione": "20 aprile 1957"
}

ANALISI PALEOGRAFICA (fonte primaria):
{
  "tipologia_documento": {
    "valore": "lettera privata",
    "confidence": 0.88,
    "fonte": "agente_analisi"
  },
  "lingua": {
    "valore": "italiano",
    "confidence": 0.93,
    "fonte": "agente_analisi"
  }
}

TRASCRIZIONE (fonte secondaria):
<archivaldescription>05.1254 bis</archivaldescription>

<transcription>
<place_sender>Ancona</place_sender>, <date>20 Aprile 1957
Vigilia di Pasqua</date>
<recipient>A Elio Fiore,</recipient>
carissimo,
ho riletta qui la tua lettera, 
che ti somiglia e quindi avvalora 
l'affetto che sento per te e la fiducia 
che ho nel tuo avvenire di poeta. Anche 
la tristezza di cui mi parli comprendo, 
anch'io l'ho vissuta e talora ancora mi 
coglie, ma i poeti sempre la domi=
nano e vincono, volta a volta. Avanti, 
Fiore! Sono contenta che i miei ottan=
t'anni dian forza alle tue venti pri=
mavere. Ti abbraccio. Sarò di ritorno 
a Roma mercoledì e ci telefoneremo. Sono 
stata un'ora al sole nel giardinetto di mio 
figlio e ho il capo un po' svagato! <sender>Sibilla</sender>
</transcription>

REGESTO CORRETTO:
Sibilla Aleramo scrive ad Elio Fiore il 20 aprile 1957 da Ancona. Esprime comprensione per la tristezza del destinatario e lo esorta a dominare questo sentimento attraverso la poesia. Si dichiara lieta che i suoi ottant'anni possano dare forza alle venti primavere del giovane poeta.

ANALISI DELLE FONTI UTILIZZATE:
{
  "mittente": "metadati_esterni",
  "destinatario": "trascrizione_tag_xml",
  "data": "metadati_esterni",
  "luogo": "trascrizione_tag_xml",
  "contenuto": "trascrizione_testo",
  "tipologia": "analisi_paleografica"
}

MOTIVAZIONE:
✓ Mittente: METADATI ESTERNI (campo "autore") - fonte primaria
✓ Data: METADATI ESTERNI (fonte primaria) - validata da tag XML
✓ Luogo: TAG XML <place_sender> - fonte secondaria affidabile
✓ Destinatario: TAG XML <recipient> - fonte secondaria affidabile
✓ Contenuto: TRASCRIZIONE testo - uso appropriato
✓ Tipologia: ANALISI PALEOGRAFICA - confidence 0.88 (affidabile)

------------------------------------------------------------

--- ESEMPIO 3 (caso con incertezza) ---

METADATI ESTERNI (fonte primaria):
{
  "tipologia": "corrispondenza"
}

ANALISI PALEOGRAFICA (fonte primaria):
{
  "tipologia_documento": {
    "valore": "lettera ufficiale",
    "confidence": 0.55,
    "fonte": "agente_analisi"
  },
  "lingua": {
    "valore": "italiano",
    "confidence": 0.90,
    "fonte": "agente_analisi"
  }
}

TRASCRIZIONE (fonte secondaria):
[testo senza tag XML chiari, scrittura difficile da decifrare]
Il sottoscritto... richiede... documentazione... 
[parti illeggibili]

REGESTO CORRETTO:
Lettera (probabilmente di carattere ufficiale) in cui il mittente richiede documentazione. La scrittura presenta numerose parti illeggibili che non permettono di identificare con certezza mittente, destinatario e data.

ANALISI DELLE FONTI UTILIZZATE:
{
  "mittente": "non_determinabile",
  "destinatario": "non_determinabile",
  "data": "non_presente",
  "contenuto": "trascrizione_testo_parziale",
  "tipologia": "analisi_paleografica_bassa_confidence"
}

NOTE: "Confidence della tipologia documento molto bassa (0.55). Trascrizione incompleta. Impossibile determinare mittente e destinatario dalle fonti disponibili."

MOTIVAZIONE:
✓ Tipologia con cautela: confidence 0.55 → uso "probabilmente"
✓ Mittente/destinatario: non presenti in metadati esterni né in tag XML → omessi
✓ Data: assente in tutte le fonti primarie → omessa
✓ Contenuto: dalla trascrizione ma segnalando lacune
✓ Note: segnala esplicitamente le limitazioni

------------------------------------------------------------

============================================================
DOCUMENTO DA ANALIZZARE:
============================================================

"""
        
        # METADATI ESTERNI (fonte primaria)
        prompt += f"\n📘 METADATI ESTERNI (fonte primaria - massima priorità):\n"
        prompt += json.dumps(context['metadati_esterni'], indent=2, ensure_ascii=False) + "\n"
        
        # ANALISI CON CONFIDENCE (fonte primaria)
        prompt += f"\n🔍 ANALISI PALEOGRAFICA E DOCUMENTARIA (fonte primaria - include confidence):\n"
        analisi_strutturata = {}
        for k, v in context['analisi'].items():
            analisi_strutturata[k] = {
                "valore": v['valore'],
                "confidence": v['confidence'],
                "fonte": v['modificato_da']
            }
        prompt += json.dumps(analisi_strutturata, indent=2, ensure_ascii=False) + "\n"
        
        # TRASCRIZIONE (fonte secondaria)
        prompt += f"\n📄 TRASCRIZIONE (fonte secondaria - potenzialmente rumorosa):\n"
        prompt += f"{context['trascrizione']}\n"
        
        prompt += """
============================================================
ISTRUZIONI FINALI PER LA CREAZIONE DEL REGESTO:
============================================================

1. Rispetta RIGOROSAMENTE la gerarchia delle fonti sopra definita
2. Per mittente, destinatario, data, luogo:
   → Priorità 1: METADATI ESTERNI
   → Priorità 2: TAG XML nella trascrizione (<sender>, <recipient>, <date>, <place_sender>)
   → Priorità 3: Testo libero (SOLO se necessario e con cautela)
   → Se impossibile determinare con certezza: OMETTI o usa formulazioni caute

3. Per tipologia documento:
   → Usa ANALISI PALEOGRAFICA (campo "tipologia_documento")
   → Se confidence ≥ 0.75: usa con fiducia
   → Se confidence < 0.6: usa formulazioni caute ("probabilmente", "sembra")

4. Per il contenuto/tema:
   → Usa la TRASCRIZIONE (è affidabile per questo scopo)
   → Sintetizza il messaggio principale in modo chiaro

5. In caso di CONFLITTO tra fonti:
   → Prevalgono SEMPRE le fonti di livello superiore
   → METADATI ESTERNI > ANALISI PALEOGRAFICA > TAG XML > TESTO LIBERO

6. Gestione incertezza:
   → Preferisci OMETTERE informazioni incerte piuttosto che inventarle
   → Se usi dati con confidence < 0.6, segnalalo con formulazioni caute
   → Se devi usare solo testo libero per info importanti, menzionalo nelle note

FORMATO OUTPUT (JSON):
{
  "regesto": "Il testo del regesto qui (max 100 parole, terza persona)...",
  "note": "Eventuali osservazioni metodologiche: fonti mancanti, incertezze, confidence basse utilizzate, etc.",
  "fonti_utilizzate": {
    "mittente": "metadati_esterni | trascrizione_tag_xml | trascrizione_testo | non_presente | non_determinabile",
    "destinatario": "metadati_esterni | trascrizione_tag_xml | trascrizione_testo | non_presente | non_determinabile",
    "data": "metadati_esterni | trascrizione_tag_xml | trascrizione_testo | non_presente | non_determinabile",
    "luogo": "metadati_esterni | trascrizione_tag_xml | trascrizione_testo | non_presente | non_determinabile",
    "contenuto": "trascrizione_testo | trascrizione_parziale",
    "tipologia": "analisi_paleografica | analisi_paleografica_bassa_confidence"
  }
}

⚠️ IMPORTANTE: 
- Compila il campo "fonti_utilizzate" con PRECISIONE per ogni informazione
- Sii ONESTO nelle note se hai dovuto usare fonti di bassa qualità
- Il regesto deve essere FATTUALE, non speculativo

Rispondi SOLO con il JSON, senza altro testo."""
        
        return prompt
    
def load_images_from_folder(folder_path: str, extensions: tuple = ('.jpg', '.jpeg', '.png')) -> List[str]:
    """Carica tutti i path delle immagini da una cartella, ordinati alfabeticamente"""
    folder = Path(folder_path)
    
    if not folder.exists():
        raise ValueError(f"La cartella non esiste: {folder_path}")
    
    if not folder.is_dir():
        raise ValueError(f"Il path non è una cartella: {folder_path}")
    
    immagini_set = set()
    for ext in extensions:
        immagini_set.update(folder.glob(f"*{ext}"))
        immagini_set.update(folder.glob(f"*{ext.upper()}"))
    
    if not immagini_set:
        raise ValueError(f"Nessuna immagine trovata nella cartella: {folder_path}")
    
    immagini_sorted = sorted([str(img.absolute()) for img in immagini_set])
    
    return immagini_sorted

class AgentMETSFormatter:
    """Agente per la formattazione e validazione dei metadati in XML-METS profilo EcoMic"""

    def __init__(self, memory: SharedMemory, llm_client: LLMClient, linee_guida_path: str):
        self.memory = memory
        self.llm = llm_client
        self.agent_type = AgentType.METS_FORMATTER
        self.linee_guida_path = linee_guida_path
        self.linee_guida_content = self._load_linee_guida()

    def _load_linee_guida(self) -> str:
        """Carica il documento delle linee guida XML-METS profilo EcoMic

        Supporta file di testo (utf-8) e file PDF. Per i PDF prova ad estrarre il testo
        usando PyPDF2 se disponibile; altrimenti restituisce un messaggio informativo
        evitando di sollevare un errore di decoding.
        """
        path = Path(self.linee_guida_path)
        if not path.exists():
            raise ValueError(f"Il file indicato non esiste: {self.linee_guida_path}")

        suffix = path.suffix.lower()
        try:
            if suffix == ".pdf":
                # Prova a estrarre testo dal PDF con PyPDF2 se disponibile
                try:
                    import PyPDF2
                    texts = []
                    with open(path, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        for page in reader.pages:
                            txt = page.extract_text()
                            if txt:
                                texts.append(txt)
                    content = "\n".join(texts).strip()
                    if not content:
                        content = f"[{path.name}] PDF caricato ma nessun testo estraibile."
                    print(f"[{self.agent_type.value}] Linee guida PDF caricate: {len(content)} caratteri (estratti)")
                    return content
                except Exception:
                    # Fallback non-istruttivo: non provare a decodificare il PDF come testo
                    msg = (f"[{path.name}] File PDF fornito. Per estrarre il testo installa PyPDF2 "
                           "(%pip install PyPDF2) o fornisci una versione testuale delle linee guida.")
                    print(f"[{self.agent_type.value}] {msg}")
                    return msg
            else:
                # Tratta come file di testo
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                print(f"[{self.agent_type.value}] Linee guida caricate: {len(content)} caratteri")
                return content

        except Exception as e:
            raise ValueError(f"Impossibile caricare linee guida da {self.linee_guida_path}: {e}")

    def formatta_mets(self) -> Dict:
        """
        Crea un file XML-METS conforme al profilo EcoMic utilizzando:
        - Metadati descrittivi inseriti manualmente
        - Metadati descrittivi analizzati dall'LLM
        - Trascrizione
        - Regesto
        - Metadati tecnici delle immagini
        """
        print(f"\n[{self.agent_type.value}] Inizio formattazione XML-METS...")

        context = self.memory.get_all_context()
        
        # Verifica che ci siano dati sufficienti
        if not context.get('trascrizione'):
            raise ValueError("Impossibile creare METS: trascrizione non disponibile")

        # System prompt con le linee guida cachate
        system_prompt = self._build_system_prompt()

        # User prompt con tutti i dati da formattare
        prompt = self._build_formatting_prompt(context)

        try:
            print(f"[{self.agent_type.value}] Chiamata API per formattazione METS...")
            
            # Chiamata text API (non serve vision qui)
            response = self.llm.call_text_api(
                prompt=prompt,
                system_prompt=system_prompt,
                response_format="json"
            )

            xml_mets = response.get("xml_mets", "")
            
            print(f"[{self.agent_type.value}] XML-METS generato ({len(xml_mets)} caratteri)")
            
            # Salva nella memoria
            self.memory._log_modifica(
                agente=self.agent_type.value,
                azione="creazione_xml_mets",
                dettagli={
                    "lunghezza": len(xml_mets),
                    "validazione": response.get("validazione", {}),
                    "warnings": response.get("warnings", [])
                }
            )

            return {
                "stato": "completato",
                "xml_mets": xml_mets,
                "validazione": response.get("validazione", {}),
                "warnings": response.get("warnings", []),
                "note": response.get("note", "")
            }

        except Exception as e:
            print(f"[{self.agent_type.value}] ❌ Errore: {e}")
            raise

    def _build_system_prompt(self) -> str:
        """Costruisce il system prompt con le linee guida (VERRÀ CACHATO)"""
        return f"""Sei un esperto archivista digitale specializzato nella creazione di metadati XML-METS conformi al profilo EcoMic.

============================================================
LINEE GUIDA XML-METS PROFILO EcoMic (DOCUMENTO DI RIFERIMENTO)
============================================================

{self.linee_guida_content}

============================================================

Il tuo compito è trasformare i metadati e le trascrizioni forniti in un file XML-METS perfettamente conforme a queste linee guida.

REGOLE FONDAMENTALI:

1. Rispetta RIGOROSAMENTE la struttura definita nelle linee guida.
2. Tutti gli elementi e attributi OBBLIGATORI nel profilo EcoMic devono essere SEMPRE presenti nel file XML,
   anche se non esplicitamente forniti nei dati di input.
3. Se un elemento obbligatorio non ha un valore disponibile:
   - inserisci un valore placeholder conforme al profilo
   - oppure un valore vuoto se consentito dallo schema
   - ma NON omettere mai l'elemento.
4. Tutti gli attributi obbligatori devono essere sempre presenti.
5. Nessun elemento richiesto dallo schema può essere omesso.
6. L'assenza di un campo nei dati NON giustifica la sua omissione se è obbligatorio nel profilo.
7. Gli ID devono essere sempre generati se mancanti.
8. Valida internamente la conformità strutturale prima di restituire l'output.

⚠️ IMPORTANTE PER IL JSON OUTPUT:
Quando restituisci il JSON con il campo "xml_mets", assicurati che:
- Tutte le virgolette nel XML siano escaped correttamente come \\"
- Tutti i newline siano rappresentati come \\n
- Non ci siano caratteri speciali non escaped
- Il JSON sia SEMPRE valido e parseable"""

    def _build_formatting_prompt(self, context: Dict) -> str:
        """Costruisce il prompt con tutti i dati da formattare"""
        
        prompt = """Crea un file XML-METS conforme al profilo EcoMic utilizzando i seguenti dati:

============================================================
DATI DISPONIBILI:
============================================================

"""
        
        # 1. Metadati descrittivi inseriti manualmente
        prompt += "\n1️⃣ METADATI DESCRITTIVI MANUALI (fonte primaria):\n"
        prompt += json.dumps(context['metadati_esterni'], indent=2, ensure_ascii=False) + "\n"
        
        # 2. Metadati descrittivi analizzati dall'LLM
        prompt += "\n2️⃣ METADATI DESCRITTIVI LLM (fonte secondaria):\n"
        analisi_semplificata = {k: v['valore'] for k, v in context['analisi'].items()}
        prompt += json.dumps(analisi_semplificata, indent=2, ensure_ascii=False) + "\n"
        
        # 3. Trascrizione
        prompt += "\n3️⃣ TRASCRIZIONE:\n"
        prompt += f"{context['trascrizione']}\n"
        
        # 4. Regesto (se disponibile)
        if hasattr(self.memory, 'regesto') and self.memory.regesto:
            prompt += "\n4️⃣ REGESTO:\n"
            prompt += f"{self.memory.regesto}\n"
        
        # 5. Metadati tecnici immagini (se disponibili)
        if hasattr(self.memory, 'metadati_tecnici_immagini'):
            prompt += "\n5️⃣ METADATI TECNICI IMMAGINI:\n"
            prompt += json.dumps(self.memory.metadati_tecnici_immagini, indent=2, ensure_ascii=False) + "\n"
        
        # 6. Informazioni sulle immagini
        prompt += "\n6️⃣ IMMAGINI:\n"
        for i, img_path in enumerate(context['immagini_paths'], 1):
            from pathlib import Path
            prompt += f"  {i}. {Path(img_path).name}\n"
        
        prompt += """
============================================================
ISTRUZIONI PER LA FORMATTAZIONE:
============================================================

1. **STRUTTURA GENERALE**:
   - Inizia con la dichiarazione XML e i namespace corretti
   - Segui la struttura: metsHdr → dmdSec → amdSec → fileSec → structMap
   - Usa gli ID nel formato specificato dalle linee guida

2. **METADATI DESCRITTIVI (dmdSec)**:
   - Privilegia i metadati manuali quando disponibili
   - Integra con i metadati LLM per campi mancanti
   - Includi il regesto se presente
   - Usa lo schema di metadati specificato nelle linee guida

3. **METADATI TECNICI (amdSec)**:
   - La sezione rightsMD è obbligatoria se prevista dal profilo.
   - Includi sempre <metsrights:RightsDeclarationMD>.
   - Includi sempre <metsrights:UserName>.
   - Includi sempre <metsrights:Context> con tutti gli attributi obbligatori:
        - CONTEXTCLASS
        - CONTEXTID
        - OTHERCONTEXTTYPE
   - Anche se i valori non sono forniti, genera valori coerenti e validi secondo il profilo.

4. **FILE SECTION (fileSec)**:
   - Elenca tutte le immagini
   - Usa percorsi relativi o assoluti come specificato
   - Includi informazioni su mimetype e dimensioni se disponibili

5. **STRUCTURAL MAP (structMap)**:
   - Rifletti la composizione logica dell'oggetto digitale
   - Usa div/@TYPE appropriati (es: page, cover, attachment)
   - Collega correttamente file e metadati

6. **TRASCRIZIONE**:
   - Includi la trascrizione nella sezione appropriata
   - Può essere inline o in un file separato secondo le linee guida
   - Mantieni i tag XML già presenti nella trascrizione

7. **VALIDAZIONE**:
   - Controlla che tutti gli ID siano univoci
   - Verifica che tutti i riferimenti (IDREF) puntino a ID esistenti
   - Assicurati che gli elementi obbligatori siano presenti
   - Segnala eventuali warnings o anomalie

============================================================
FORMATO OUTPUT (JSON):
============================================================

⚠️ ATTENZIONE CRITICA PER L'ESCAPING:
Nel JSON che restituisci, il campo "xml_mets" contiene XML come stringa.
DEVI ASSICURARTI che:
1. Ogni virgoletta (") nel XML sia escaped come \\"
2. Ogni newline sia rappresentato come \\n (due backslash + n)
3. Ogni backslash nel XML sia escaped come \\\\
4. Il JSON risultante sia SEMPRE valido e parseable

ESEMPIO CORRETTO:
{
  "xml_mets": "<?xml version=\\"1.0\\" encoding=\\"UTF-8\\"?>\\n<mets:mets>\\n  <element attr=\\"value\\"/>\\n</mets:mets>",
  "validazione": { ... },
  "warnings": [ ... ],
  "note": "..."
}

{
  "xml_mets": "[STRINGA XML COMPLETA QUI - BEN FORMATA E ESCAPED]",
  "validazione": {
    "conforme": true,
    "elementi_obbligatori_presenti": true,
    "id_univoci": true,
    "riferimenti_validi": true
  },
  "warnings": [
    "Metadato 'luogo' non disponibile - campo omesso",
    "Metadati tecnici immagine 2 non disponibili"
  ],
  "note": "Eventuali osservazioni sulla formattazione o scelte interpretative"
}

⚠️ IMPORTANTE:
- Il campo "xml_mets" deve contenere l'INTERO file XML come stringa CORRETTAMENTE ESCAPED
- OGNI virgoletta nel XML deve essere \\"
- OGNI newline deve essere \\n
- Assicurati che l'XML sia ben formato e valido
- Segnala nei warnings eventuali informazioni mancanti o decisioni interpretative

Rispondi SOLO con il JSON, senza altro testo."""

        return prompt

    def salva_xml(self, xml_content: str, output_path: str):
        """Salva il file XML-METS su disco"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            print(f"[{self.agent_type.value}] ✓ XML-METS salvato in: {output_path}")
        except Exception as e:
            print(f"[{self.agent_type.value}] ❌ Errore nel salvataggio: {e}")
            raise


class Orchestrator:
    """Orchestratore che coordina gli agenti e gestisce il workflow"""

    def __init__(self, llm_provider: str = "anthropic", api_key: Optional[str] = None,
                 preprocess_images: bool = True, contrast_factor: float = 2.0,
                 save_preview: bool = False, preview_folder: str = "./preview",
                 use_prompt_caching: bool = True, linee_guida_mets_path: Optional[str] = None):
        """
        Inizializza l'orchestratore con le configurazioni necessarie
        
        Args:
            llm_provider: Provider LLM da utilizzare (default: "anthropic")
            api_key: Chiave API per il provider LLM
            preprocess_images: Se True, converte immagini in B&W e aumenta contrasto
            contrast_factor: Fattore di aumento contrasto (1.0-3.0, default 2.0)
            save_preview: Se True, salva le immagini preprocessate per visualizzarle
            preview_folder: Cartella dove salvare le preview (default "./preview")
            use_prompt_caching: Se True, usa Prompt Caching di Anthropic per ridurre costi
        """
        self.memory = SharedMemory()
        self.llm_client = LLMClient(
            provider=llm_provider, 
            api_key=api_key,
            use_prompt_caching=use_prompt_caching
        )
        
        self.preprocess_images = preprocess_images
        self.contrast_factor = contrast_factor
        self.save_preview = save_preview
        self.preview_folder = preview_folder
        self.use_prompt_caching = use_prompt_caching
        self.metadati_completi_file = None
        
        # Crea gli agenti e passa le impostazioni di preprocessing
        self.agent_analysis = AgentAnalysis(self.memory, self.llm_client)
        self.agent_analysis._orchestrator_settings = {
            'preprocess': preprocess_images,
            'contrast': contrast_factor,
            'save_preview': save_preview,
            'preview_folder': preview_folder
        }
        
        self.agent_transcription = AgentTranscription(self.memory, self.llm_client)
        self.agent_transcription._orchestrator_settings = {
            'preprocess': preprocess_images,
            'contrast': contrast_factor,
            'save_preview': save_preview,
            'preview_folder': preview_folder
        }
        
        self.agent_regesto = AgentRegesto(self.memory, self.llm_client)
        
        # Inizializza l'agente METS solo se fornito il path alle linee guida
        if linee_guida_mets_path:
            self.agent_mets = AgentMETSFormatter(
                self.memory, 
                self.llm_client,
                linee_guida_mets_path
            )
        else:
            self.agent_mets = None
            print("[ORCHESTRATOR] ⚠️ Agente METS non inizializzato (linee_guida_mets_path non fornito)")  
       

    def process_manuscript(self, metadati_file: str,
                          cartella_immagini: str,
                          metadati_completi_file: Optional[str] = None,
                          genera_mets: bool = False,
                          output_mets_path: Optional[str] = None) -> Dict:
        """
        Processo completo: dall'input al risultato finale
        
        Args:
            metadati_file: Path al file JSON con i metadati descrittivi essenziali
            cartella_immagini: Path alla cartella contenente le immagini del manoscritto
            metadati_completi_file: Path al file JSON con metadati tecnici completi (opzionale)
            genera_mets: Se True, genera anche il file XML-METS
            output_mets_path: Path dove salvare l'XML-METS (opzionale)
        
        Returns:
            Dict contenente metadati, trascrizione, regesto e METS (se richiesto)
        """
        print("="*60)
        print("INIZIO ORCHESTRAZIONE")
        print("="*60)

        # 1. Carica metadati esterni (essenziali)
        with open(metadati_file, 'r', encoding='utf-8') as f:
            metadati = json.load(f)
        
        # Estrai i metadati dal primo (e unico) oggetto
        for key, value in metadati.items():
            if isinstance(value, dict) and "metadati_descrittivi" in value:
                metadati_descrittivi = value["metadati_descrittivi"]
                break
        else:
            metadati_descrittivi = metadati
        
        self.memory.set_metadati_esterni(metadati_descrittivi)
        
        # 1b. Salva il path dei metadati completi per uso successivo
        self.metadati_completi_file = metadati_completi_file

        # 2. Carica immagini dalla cartella
        immagini_paths = load_images_from_folder(cartella_immagini)
        self.memory.set_immagini(immagini_paths)
        
        print(f"\n📁 Caricate {len(immagini_paths)} immagini:")
        for i, path in enumerate(immagini_paths, 1):
            print(f"  {i}. {Path(path).name}")
        
        if self.preprocess_images:
            print(f"\n🖼️  PREPROCESSING ATTIVO:")
            print(f"  - Conversione in bianco e nero")
            print(f"  - Aumento contrasto: {self.contrast_factor}x")
            if self.save_preview:
                print(f"  - Preview salvate in: {self.preview_folder}/")

        # 3. Analisi iniziale (CREA la cache)
        print("\n" + "="*60)
        print("FASE 1: ANALISI (crea cache)")
        print("="*60)
        self.agent_analysis.analyze()

        # 4. Trascrizione CON VALIDAZIONE contro metadati esterni (USA la cache!)
        print("\n" + "="*60)
        print("FASE 2: TRASCRIZIONE (usa cache + validazione metadati esterni)")
        print("="*60)

        risultato_trascrizione = self.agent_transcription.transcribe()
        
        # Stampa eventuali correzioni applicate
        if risultato_trascrizione.get("correzioni_applicate"):
            print("\n⚠️ CORREZIONI APPLICATE basate su metadati esterni:")
            for correzione in risultato_trascrizione["correzioni_applicate"]:
                print(f"  • {correzione}")
        
        # Stampa eventuali contraddizioni rilevate
        if risultato_trascrizione.get("contraddizioni_rilevate"):
            print("\n⚠️ CONTRADDIZIONI RILEVATE e risolte:")
            for contraddizione in risultato_trascrizione["contraddizioni_rilevate"]:
                print(f"  • Campo '{contraddizione['campo']}':")
                print(f"    - Visto nel documento: {contraddizione['valore_visto_documento']}")
                print(f"    - Metadati esterni: {contraddizione['valore_metadati_esterni']}")
                print(f"    - Azione: {contraddizione['azione']}")
        
        print("\n✓ Trascrizione completata!")

        # 5. Crea il regesto con gerarchia epistemica (SOLO TEXT - no vision)
        print("\n" + "="*60)
        print("FASE 3: REGESTO (solo text)")
        print("="*60)
        
        regesto_risultato = None
        if self.memory.trascrizione:
            try:
                regesto_risultato = self.agent_regesto.crea_regesto()
                
                # Stampa le fonti utilizzate per debug
                if regesto_risultato and "fonti_utilizzate" in regesto_risultato:
                    print(f"\n📊 Fonti utilizzate per il regesto:")
                    for campo, fonte in regesto_risultato["fonti_utilizzate"].items():
                        print(f"  • {campo}: {fonte}")
                    
                # Stampa eventuali note metodologiche
                if regesto_risultato and regesto_risultato.get("note"):
                    print(f"\n📝 Note metodologiche: {regesto_risultato['note']}")
                        
            except Exception as e:
                print(f"\n⚠️ Errore nella creazione del regesto: {e}")
                

        # 6. FASE METS: Formattazione METS (opzionale)
        mets_risultato = None
        if genera_mets:
            if not self.agent_mets:  
                print("\n⚠️ METS richiesto ma agente METS non inizializzato")
                print("   Fornisci linee_guida_mets_path al costruttore dell'Orchestrator")
            else: 
                print("\n" + "="*60)
                print("FASE 4: FORMATTAZIONE XML-METS")
                print("="*60)
            
                try:
                    # Aggiungi regesto e metadati tecnici alla memoria se disponibili
                    if regesto_risultato:
                        self.memory.regesto = regesto_risultato.get("regesto")
                    
                    if self.metadati_completi_file:
                        metadati_tecnici = self._carica_metadati_tecnici()
                        if metadati_tecnici:
                            self.memory.metadati_tecnici_immagini = metadati_tecnici
                    
                    # Genera METS
                    mets_risultato = self.agent_mets.formatta_mets()
                    
                    # Salva su file
                    if output_mets_path is None:
                        output_mets_path = "output_mets.xml"
                    
                    self.agent_mets.salva_xml(
                        mets_risultato['xml_mets'],
                        output_mets_path
                    )
                    
                    print(f"\n✓ XML-METS salvato in: {output_mets_path}")
                    
                    # Mostra validazione
                    if mets_risultato.get('validazione'):
                        print(f"\n📋 Validazione METS:")
                        for k, v in mets_risultato['validazione'].items():
                            status = "✓" if v else "✗"
                            print(f"  {status} {k}: {v}")
                    
                    # Mostra warnings
                    if mets_risultato.get('warnings'):
                        print(f"\n⚠️ Warnings ({len(mets_risultato['warnings'])}):")
                        for warning in mets_risultato['warnings']:
                            print(f"  • {warning}")
                            
                except Exception as e:
                    print(f"\n⚠️ Errore nella generazione METS: {e}")
                    import traceback
                    traceback.print_exc()
        
        # Prepara output finale (includi METS se generato)
        output = self._prepara_output(risultato_trascrizione, regesto_risultato, mets_risultato)
        
        return output

    def _carica_metadati_tecnici(self) -> Optional[Dict]:
        """Carica i metadati tecnici dal file metadati_completi.json"""
        if not self.metadati_completi_file:
            print("[INFO] Nessun file metadati_completi specificato")
            return None
        
        try:
            print(f"[INFO] Caricamento metadati tecnici da: {self.metadati_completi_file}")
            
            with open(self.metadati_completi_file, 'r', encoding='utf-8') as f:
                dati_completi = json.load(f)
            
            # Estrai la sezione immagini
            # Il formato è: {CNMD...: {"metadati_descrittivi": ..., "immagini": [...], "statistiche": ...}}
            for chiave, contenuto in dati_completi.items():
                if "immagini" in contenuto:
                    return {
                        "immagini": contenuto["immagini"],
                        "statistiche": contenuto.get("statistiche", {})
                    }
            
            return None
            
        except Exception as e:
            print(f"[WARNING] Errore nel caricamento metadati tecnici: {e}")
            return None

    def _prepara_output(self, risultato_trascrizione: Dict, regesto_risultato: Optional[Dict] = None, mets_risultato: Optional[Dict] = None) -> Dict:
        """Prepara l'output finale con metadati (descrittivi + tecnici), trascrizione, regesto e METS"""
        context = self.memory.get_all_context()
        
        # Estrai solo i valori dai metadati analizzati, senza confidence e versioni precedenti
        metadati_analizzati = {}
        for chiave, dati in context["analisi"].items():
            metadati_analizzati[chiave] = dati["valore"]
        
        # Carica i metadati tecnici se disponibili
        metadati_tecnici = self._carica_metadati_tecnici()
        
        # Output completo
        output = {
            "metadati_descrittivi_inseriti_manualmente": context["metadati_esterni"],
            "metadati_descrittivi_LLM": metadati_analizzati,
            "trascrizione": self.memory.trascrizione or ""
        }
        
        # Aggiungi informazioni sulla trascrizione (correzioni, contraddizioni)
        if risultato_trascrizione.get("correzioni_applicate"):
            output["trascrizione_correzioni_applicate"] = risultato_trascrizione["correzioni_applicate"]
        
        if risultato_trascrizione.get("contraddizioni_rilevate"):
            output["trascrizione_contraddizioni_rilevate"] = risultato_trascrizione["contraddizioni_rilevate"]
        
        if risultato_trascrizione.get("aree_incerte"):
            output["trascrizione_aree_incerte"] = risultato_trascrizione["aree_incerte"]
        
        # Aggiungi il regesto se disponibile
        if regesto_risultato and regesto_risultato.get("regesto"):
            output["regesto"] = regesto_risultato["regesto"]
            
            # Aggiungi anche le fonti utilizzate per il regesto (utile per debugging e validazione)
            if "fonti_utilizzate" in regesto_risultato:
                output["regesto_fonti_utilizzate"] = regesto_risultato["fonti_utilizzate"]
            
            # Aggiungi il metodo usato
            if "metodo" in regesto_risultato:
                output["regesto_metodo"] = regesto_risultato["metodo"]
            
            # Aggiungi note metodologiche se presenti
            if "note" in regesto_risultato and regesto_risultato["note"]:
                output["regesto_note_metodologiche"] = regesto_risultato["note"]
        
        # Aggiungi il METS XML se disponibile
        if mets_risultato and mets_risultato.get("xml_mets"):
            output["mets_xml"] = mets_risultato["xml_mets"]
            
            # Aggiungi warnings se presenti
            if mets_risultato.get("warnings"):
                output["mets_warnings"] = mets_risultato["warnings"]
        
        # Aggiungi metadati tecnici se disponibili
        if metadati_tecnici:
            output["metadati_tecnici"] = metadati_tecnici
        
        return output

    def print_report(self, output: Dict):
        """Stampa un report leggibile del risultato"""
        print("\n" + "="*60)
        print("REPORT FINALE")
        print("="*60)

        print("\n📊 METADATI DESCRITTIVI ANALIZZATI:")
        for chiave, valore in output['metadati_descrittivi_LLM'].items():
            val_str = str(valore)
            if len(val_str) > 100:
                val_str = val_str[:100] + "..."
            print(f"  {chiave}: {val_str}")

        if "metadati_tecnici" in output:
            print("\n🔧 METADATI TECNICI:")
            stats = output['metadati_tecnici'].get('statistiche', {})
            print(f"  Numero immagini: {stats.get('numero_immagini', 0)}")
            if output['metadati_tecnici'].get('immagini'):
                print(f"  Dettagli immagini disponibili: {len(output['metadati_tecnici']['immagini'])}")

        print("\n📄 TRASCRIZIONE:")
        if output.get('trascrizione'):
            trascrizione = output['trascrizione']
            if len(trascrizione) > 400:
                print(f"  {trascrizione[:400]}...")
                print(f"  [...trascrizione completa: {len(trascrizione)} caratteri totali]")
            else:
                print(f"  {trascrizione}")
        else:
            print("  Nessuna trascrizione disponibile")
        
        # Mostra correzioni applicate nella trascrizione
        if "trascrizione_correzioni_applicate" in output and output["trascrizione_correzioni_applicate"]:
            print("\n⚠️ CORREZIONI APPLICATE NELLA TRASCRIZIONE:")
            for correzione in output["trascrizione_correzioni_applicate"]:
                print(f"  • {correzione}")
        
        # Mostra contraddizioni rilevate nella trascrizione
        if "trascrizione_contraddizioni_rilevate" in output and output["trascrizione_contraddizioni_rilevate"]:
            print("\n⚠️ CONTRADDIZIONI RILEVATE E RISOLTE:")
            for contraddizione in output["trascrizione_contraddizioni_rilevate"]:
                print(f"  • Campo '{contraddizione['campo']}':")
                print(f"    Visto: {contraddizione['valore_visto_documento']}")
                print(f"    Corretto con: {contraddizione['valore_metadati_esterni']}")
        
        # Regesto
        if "regesto" in output:
            print("\n📋 REGESTO:")
            print(f"  {output['regesto']}")
            
            # Mostra il metodo usato
            if "regesto_metodo" in output:
                print(f"\n  Metodo: {output['regesto_metodo']}")
            
            # Mostra le fonti utilizzate (importante per validazione)
            if "regesto_fonti_utilizzate" in output:
                print(f"\n  📊 Fonti utilizzate:")
                for campo, fonte in output['regesto_fonti_utilizzate'].items():
                    print(f"    • {campo}: {fonte}")
            
            # Mostra note metodologiche se presenti
            if "regesto_note_metodologiche" in output:
                print(f"\n  📝 Note metodologiche: {output['regesto_note_metodologiche']}")
        
        # Mostra info METS se presente
        if "mets_xml" in output:
            print("\n📄 XML-METS:")
            print(f"  Generato ({len(output['mets_xml'])} caratteri)")
            if "mets_warnings" in output and output["mets_warnings"]:
                print(f"  Warnings: {len(output['mets_warnings'])}")
