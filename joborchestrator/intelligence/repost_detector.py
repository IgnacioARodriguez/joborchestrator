"""
Repost Detector: Detecta ofertas que fueron publicadas múltiples veces.

Util para identificar si una empresa está re-publicando una oferta (potencial ghost job)
o si es la misma oferta en diferentes sitios.
"""

from typing import List, Dict, Tuple
import hashlib
from difflib import SequenceMatcher


def normalize_text(text: str) -> str:
    """
    Normaliza texto para comparación: lowercase, sin espacios extra, sin puntuación.
    """
    if not text:
        return ""
    text = text.lower()
    text = " ".join(text.split())  # Remove extra spaces
    # Remove common punctuation but keep structure
    text = text.replace(".", " ").replace(",", " ").replace("!", " ").replace("?", " ")
    return text


def compute_job_hash(job: Dict) -> str:
    """
    Computa un hash de la oferta basado en título, empresa, descripción.
    Dos ofertas con el mismo hash son probablemente la misma.
    """
    title = job.get('titulo') or job.get('title', '')
    company = job.get('empresa') or job.get('company', '')
    description = (job.get('descripcion') or job.get('description', ''))[:500]  # Primeros 500 chars
    
    combined = f"{normalize_text(title)}{normalize_text(company)}{normalize_text(description)}"
    return hashlib.md5(combined.encode()).hexdigest()


def similarity_score(text1: str, text2: str) -> float:
    """
    Calcula similaridad entre dos textos (0-1).
    """
    if not text1 or not text2:
        return 0.0
    
    text1 = normalize_text(text1)
    text2 = normalize_text(text2)
    
    return SequenceMatcher(None, text1, text2).ratio()


def detect_reposts(jobs: List[Dict]) -> Dict:
    """
    Detecta reposts en un lote de ofertas.
    
    Retorna dict con:
    - repost_groups: Lista de grupos de ofertas similares
    - single_postings: Ofertas únicas
    - stats: Estadísticas
    """
    if not jobs:
        return {
            "repost_groups": [],
            "single_postings": [],
            "stats": {"total": 0, "reposts": 0, "unique": 0},
        }
    
    # Primera pasada: agrupar por hash exacto
    hash_groups = {}
    for job in jobs:
        job_hash = compute_job_hash(job)
        if job_hash not in hash_groups:
            hash_groups[job_hash] = []
        hash_groups[job_hash].append(job)
    
    # Segunda pasada: detectar similares (fuzzy matching para hashes diferentes)
    repost_groups = []
    processed_hashes = set()
    
    for hash1, group1 in hash_groups.items():
        if hash1 in processed_hashes:
            continue
        
        current_group = list(group1)
        group_similarity = 1.0
        processed_hashes.add(hash1)
        
        # Buscar similares en otros hashes
        for hash2, group2 in hash_groups.items():
            if hash2 == hash1 or hash2 in processed_hashes:
                continue
            
            # Comparar título + descripción
            title_sim = similarity_score(
                group1[0].get('titulo') or group1[0].get('title', ''),
                group2[0].get('titulo') or group2[0].get('title', '')
            )
            desc_sim = similarity_score(
                (group1[0].get('descripcion') or group1[0].get('description', ''))[:300],
                (group2[0].get('descripcion') or group2[0].get('description', ''))[:300]
            )
            
            # Si ambos son similares (>70%), es un repost
            combined_sim = (title_sim * 0.4) + (desc_sim * 0.6)
            
            if combined_sim > 0.70:
                current_group.extend(group2)
                processed_hashes.add(hash2)
                group_similarity = max(group_similarity, combined_sim)
        
        # Si el grupo tiene >1 oferta, es un repost
        if len(current_group) > 1:
            seen_dates = [
                job.get('fecha_publicada') or job.get('posted_date')
                for job in current_group
                if job.get('fecha_publicada') or job.get('posted_date')
            ]
            repost_groups.append({
                "master_job": current_group[0],  # La primera es "maestra"
                "count": len(current_group),
                "duplicates": current_group[1:],
                "similarity": group_similarity,
                "first_seen": current_group[0].get('fecha_publicada') or current_group[0].get('posted_date'),
                "last_seen": max(seen_dates, default=None),
            })
        else:
            processed_hashes.add(hash1)
    
    # Las ofertas no marcadas son únicas
    single_postings = []
    for group in hash_groups.values():
        if len(group) == 1 and compute_job_hash(group[0]) not in [
            compute_job_hash(rg["master_job"]) for rg in repost_groups
        ]:
            single_postings.extend(group)
    
    return {
        "repost_groups": repost_groups,
        "single_postings": single_postings,
        "stats": {
            "total": len(jobs),
            "repost_groups": len(repost_groups),
            "total_reposts": sum(rg["count"] for rg in repost_groups),
            "unique": len(single_postings) + len(repost_groups),
            "unique_count": len(single_postings),
            "master_count": len(repost_groups),
            "repost_count": sum(len(rg["duplicates"]) for rg in repost_groups),
        },
    }


def mark_repost_status(jobs: List[Dict]) -> List[Dict]:
    """
    Marca cada oferta con su status de repost.
    
    Retorna lista con `repost_info` agregado:
    - status: "unique" / "repost" / "master"
    - group_id: ID del grupo (si es repost)
    - repost_count: Cuántas veces fue publicada
    """
    result = []
    repost_data = detect_reposts(jobs)
    
    # Marcar masters
    master_ids = {compute_job_hash(rg["master_job"]) for rg in repost_data["repost_groups"]}
    
    for job in jobs:
        job_copy = job.copy()
        job_hash = compute_job_hash(job)
        
        # Buscar en qué grupo está
        group_found = None
        for rg in repost_data["repost_groups"]:
            if (compute_job_hash(rg["master_job"]) == job_hash or
                any(compute_job_hash(dup) == job_hash for dup in rg["duplicates"])):
                group_found = rg
                break
        
        if group_found:
            if compute_job_hash(group_found["master_job"]) == job_hash:
                job_copy["repost_info"] = {
                    "status": "master",
                    "repost_count": group_found["count"],
                    "last_reposted": group_found["last_seen"],
                    "recommendation": f"⚠️ This posting has been republished {group_found['count']} times. Check dates for activity."
                }
            else:
                job_copy["repost_info"] = {
                    "status": "repost",
                    "repost_count": group_found["count"],
                    "master_url": group_found["master_job"].get('url', ''),
                    "recommendation": "🔁 Duplicate posting. Apply to master listing instead."
                }
        else:
            job_copy["repost_info"] = {
                "status": "unique",
                "repost_count": 1,
                "recommendation": "✅ First time posting. Likely fresh opportunity."
            }
        
        result.append(job_copy)
    
    return result


def filter_by_repost_status(jobs: List[Dict], status: str = "unique") -> List[Dict]:
    """
    Filtra ofertas por status de repost.
    
    status puede ser: "unique", "master", "repost", o "any" (retorna todos marcados)
    """
    marked = mark_repost_status(jobs)
    
    if status == "any":
        return marked
    
    return [j for j in marked if j.get("repost_info", {}).get("status") == status]
