import os
import json
import pickle
import numpy as np
from sentence_transformers import SentenceTransformer
import faiss

# ----------------------------------------------------------------------
# ABSOLUTE PATH CONFIGURATION (PATHS ARE WORKING PER YOUR LOGS)
# ----------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "rag_data")

JSONL_PATH = os.path.join(DATA_DIR, "ssuet_pages.jsonl")
INDEX_PATH = os.path.join(DATA_DIR, "faiss_index.bin")
META_PATH  = os.path.join(DATA_DIR, "metadata.pkl")

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 500          # characters per chunk
CHUNK_OVERLAP = 50        # overlap to avoid losing context at borders
TOP_K = 3                 # how many chunks to return at query time
# ----------------------------------------------------------------------


class SSUETRAG:
    def __init__(self):
        self.model = SentenceTransformer(EMBEDDING_MODEL)
        self.index = None
        self.metadata = []          # parallel list: dict per vector
        self._load_or_create_index()

    # --------------------------------------------------------------
    def _load_or_create_index(self):
        # 👇 PATHS ARE WORKING - KEEPING DEBUG FOR VERIFICATION
        print(f"\n🔍 RAG ENGINE PATH DEBUG:")
        print(f"   Script directory: {SCRIPT_DIR}")
        print(f"   Data directory:   {DATA_DIR}")
        print(f"   Looking for index: {os.path.exists(INDEX_PATH)}")
        print(f"   Looking for meta:  {os.path.exists(META_PATH)}")
        
        if os.path.exists(INDEX_PATH) and os.path.exists(META_PATH):
            try:
                self.index = faiss.read_index(INDEX_PATH)
                with open(META_PATH, "rb") as f:
                    self.metadata = pickle.load(f)
                print(f"📚 LOADED EXISTING RAG INDEX: {len(self.metadata)} chunks")
                # 👇 DEBUG: Show first entry to verify structure
                if self.metadata:
                    first_entry = self.metadata[0]
                    title_preview = first_entry.get('title', 'NO TITLE')[:60]
                    content_preview = first_entry.get('content_text', 'NO CONTENT')[:60]
                    print(f"   🔍 FIRST ENTRY - Title: {title_preview}")
                    print(f"   🔍 FIRST ENTRY - Content (chairperson info): {content_preview}")
            except Exception as e:
                print(f"⚠️  Failed to load index ({e}); creating a new one.")
                self._create_new_index()
        else:
            print(f"❌ INDEX FILES NOT FOUND AT EXPECTED LOCATION!")
            print(f"   Expected index: {INDEX_PATH}")
            print(f"   Expected meta:  {META_PATH}")
            print(f"   Creating new empty index...")
            self._create_new_index()

    def _create_new_index(self):
        dim = self.model.get_sentence_embedding_dimension()
        self.index = faiss.IndexFlatL2(dim)   # simple L2 distance index
        self.metadata = []
        print(f"🆕 CREATED NEW FAISS INDEX (dim={dim})")

    # --------------------------------------------------------------
    def _chunk_text(self, text: str):
        """Yield overlapping chunks of text."""
        start = 0
        text_len = len(text)
        while start < text_len:
            end = start + CHUNK_SIZE
            yield text[start:end]
            start = end - CHUNK_OVERLAP
            if start < 0:
                start = 0

    # --------------------------------------------------------------
    def add_documents(self):
        """Read the JSONL file, chunk title+content together for embedding, store full content for context."""
        if not os.path.isfile(JSONL_PATH):
            raise FileNotFoundError(f"Cannot find {JSONL_PATH}")

        print(f"📥 LOADING DOCUMENTS FROM {JSONL_PATH}")
        docs = []
        with open(JSONL_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    docs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue   # skip malformed lines

        print(f"   📄 {len(docs)} PAGES LOADED FROM JSONL")

        all_chunks = []
        new_meta = []

        for doc in docs:
            url = doc.get("url", "")
            title = doc.get("title", "")
            content = doc.get("content", "")

            print(f"   🔎 PROCESSING DOC: {title[:50]}... (Title: {len(title)} chars, Content: {len(content)} chars)")

            # Embed title + content together so both faculty names AND page content are searchable
            combined_text = f"{title}\n{content}" if title else content

            for i, chunk in enumerate(self._chunk_text(combined_text)):
                if len(chunk.strip()) < 20:   # ignore tiny chunks
                    continue
                all_chunks.append(chunk)
                new_meta.append({
                    "url": url,
                    "title": title,
                    "content": chunk,        # the chunk that was embedded (used for similarity)
                    "content_text": content, # full original page content for context building
                    "chunk_id": i,
                })

        if not all_chunks:
            print("⚠️  NO USABLE CHUNKS FOUND – NOTHING TO INDEX.")
            return

        print(f"🔢 GENERATING EMBEDDINGS FOR {len(all_chunks)} CHUNKS …")
        embeddings = self.model.encode(all_chunks, show_progress_bar=True,
                                       convert_to_numpy=True, normalize_embeddings=False)

        self.index.add(np.array(embeddings).astype("float32"))
        self.metadata.extend(new_meta)

        self._save_index()
        print(f"✅ ADDED {len(all_chunks)} CHUNKS. TOTAL VECTORS: {self.index.ntotal}")

    # --------------------------------------------------------------
    def _save_index(self):
        faiss.write_index(self.index, INDEX_PATH)
        with open(META_PATH, "wb") as f:
            pickle.dump(self.metadata, f)
        print(f"💾 INDEX SAVED TO {INDEX_PATH}")

    # --------------------------------------------------------------
    def retrieve(self, query: str, k: int = 50) -> list:  # 👇 KEPT AT 50 FOR BALANCE (ADJUST IF NEEDED)
        """Return the top‑k most similar chunks (as dicts). WITH DEBUG."""
        if self.index.ntotal == 0:
            print("⚠️  RETRIEVE CALLED BUT INDEX IS EMPTY!")
            return []
        
        print(f"\n🔍 RETRIEVAL START | Query: '{query}'")
        q_emb = self.model.encode([query], convert_to_numpy=True)
        q_emb = np.array(q_emb).astype("float32")
        distances, indices = self.index.search(q_emb, k)
        
        print(f"   RAW SEARCH RESULTS (top {min(k, 10)}):")
        for rank, (idx, dist) in enumerate(zip(indices[0], distances[0]), 1):
            if idx < len(self.metadata):
                meta = self.metadata[idx]
                # SHOW TITLE PROMINENTLY (NOW CONTAINS THE ENTITY NAME WE MATCHED ON)
                title_preview = meta.get('title', '')[:80].replace('\n', ' ')
                content_preview = meta.get('content', '')[:80].replace('\n', ' ')
                content_text_preview = meta.get('content_text', '')[:80].replace('\n', ' ')
                similarity = 1.0 / (1.0 + dist)
                print(f"     #{rank}: Dist={dist:.4f} | Sim={similarity:.4f} | Idx={idx}")
                print(f"          Title: {title_preview}")  # THIS IS WHAT WE MATCHED ON (FACULTY NAME)
                print(f"          Stored Content (chunked title): {content_preview}")
                print(f"          Original Content: {content_text_preview}...")
            else:
                print(f"     #{rank}: INVALID IDX {idx} (>= {len(self.metadata)})")
                break  # Stop at first invalid idx
        
        results = []
        for idx, dist in zip(indices[0], distances[0]):
            if idx < len(self.metadata):
                meta = self.metadata[idx].copy()
                meta["similarity_score"] = float(1.0 / (1.0 + dist))  # 0‑1 similarity
                results.append(meta)
        
        print(f"   ✅ RETURNING {len(results)} VALID RESULTS\n")
        return results

    # --------------------------------------------------------------
    def get_context_prompt(self, query: str, max_chars: int = 5000) -> str:  # 👇 SAFE MAX_CHARS FOR CONTEXT
        """
        Build a context string to prepend to the system prompt.
        NOW USES TITLE-BASED EMBEDDING FOR BETTER ENTITY MATCHING.
        """
        print(f"\n📝 BUILDING CONTEXT PROMPT FOR: '{query}'")
        chunks = self.retrieve(query, k=50)  # Match the k above
        
        if not chunks:
            print("   ❌ NO CHUNKS RETRIEVED – RETURNING EMPTY CONTEXT")
            return ""

        parts = []
        cur_len = 0
        print(f"   📦 ATTEMPTING TO BUILD CONTEXT (max {max_chars} chars)")
        
        for i, ch in enumerate(chunks, 1):
            src = f"[Source: {ch['title']} ({ch['url']})]"
            # USE ORIGINAL CONTENT (chairperson info, etc.) FOR CONTEXT BODY
            txt = ch.get("content_text", "").strip()
            if not txt:
                txt = ch.get("content", "").strip()
                
            block = f"{src}\n{txt}\n"
            block_len = len(block)
            
            if cur_len + block_len > max_chars:
                # Calculate available remaining characters for this block
                remaining_space = max_chars - cur_len - len(src) - 50
                if remaining_space > 200:  # Only add if we can fit a meaningful sentence
                    truncated_txt = txt[:remaining_space] + "... [Content truncated to fit context limits]"
                    block = f"{src}\n{truncated_txt}\n"
                    parts.append(block)
                    cur_len += len(block)
                    print(f"      ✅ ADDED TRUNCATED CHUNK {i} | Length: {len(block)} | Total: {cur_len}")
                else:
                    print(f"      ⏹️  STOPPING AT CHUNK {i} (would exceed {max_chars} chars)")
                break
                
            parts.append(block)
            cur_len += block_len
            print(f"      ✅ ADDED CHUNK {i} | Length: {block_len} | Total: {cur_len}")
            print(f"         Preview: {txt[:60]}...")

        if not parts:
            print("   ❌ NO PARTS ADDED TO CONTEXT – RETURNING EMPTY")
            return ""
            
        header = "=== RETRIEVED CONTEXT FROM SSUET WEBSITE ===\n"
        footer = "=== END OF RETRIEVED CONTEXT ===\n"
        context_string = header + "".join(parts) + footer
        
        print(f"   🎉 CONTEXT BUILT SUCCESSFULLY!")
        print(f"      Final length: {len(context_string)} chars")
        print(f"      Preview: {context_string[:200]}...")
        
        return context_string


# ----------------------------------------------------------------------
# Helper for command‑line use
# ----------------------------------------------------------------------
def build_index():
    rag = SSUETRAG()
    rag.add_documents()


if __name__ == "__main__":
    build_index()