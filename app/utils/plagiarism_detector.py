from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable


ENTITY_TOKEN = "[ENTITY_REPLACED]"

ZH_STOPWORDS = {
    "的", "了", "在", "是", "和", "与", "及", "或", "也", "都", "而", "并", "对", "从",
    "到", "中", "为", "将", "把", "被", "一个", "一种", "这个", "那个", "这些", "那些",
    "我们", "他们", "因为", "所以", "但是", "如果", "通过", "进行", "对于", "关于",
}

EN_STOPWORDS = {
    "a", "an", "the", "of", "with", "to", "in", "on", "at", "by", "as", "is", "it", "its",
    "be", "been", "being", "and", "or", "for", "from", "that", "this", "these", "those",
    "are", "was", "were", "have", "has", "had", "not", "but", "if", "than", "then", "there",
    "here", "who", "whom", "which", "what", "when", "where", "why", "how", "also", "very",
    "just", "into", "over", "under", "between", "after", "before", "during", "without",
}

POLICY_PATTERNS = [
    r"《[^》]{2,80}(?:法|条例|办法|规定|通知|意见|方案|规划|纲要|细则|白皮书)》",
    r"(?:关于|中共中央|国务院)[\u4e00-\u9fa5]{4,80}(?:通知|意见|决定|方案|规划|办法)",
    r"[A-Z][A-Za-z ]{4,80}(?:Act|Bill|Law|Regulation|Policy|Guidance|Order)",
]

ORG_SUFFIX_RE = (
    r"(?:有限公司|股份有限公司|集团|公司|大学|学院|研究院|委员会|协会|基金会|政府|"
    r"人民政府|办公厅|办公室|生态环境部|财政部|商务部|发改委|证监会|银行|医院|"
    r"平台|工作室|团队|机构|组织|Department|Ministry|Committee|Association|"
    r"Foundation|University|Bank|Inc|Corp|Corporation|Ltd|LLC|Group)"
)

LOC_SUFFIX_RE = r"(?:省|市|自治区|特别行政区|区|县|州|盟|旗|镇|乡|村|街道|高新区|新区|开发区|工业园|自贸区)"

ZH_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻"
    "柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺"
    "倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚"
    "邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋庞熊纪舒屈项祝董梁杜阮蓝闵"
    "席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田胡凌霍虞万"
    "支柯管卢莫房裘缪解应宗丁宣邓杭洪包左石崔龚程邢陆翁荀惠甄曲"
    "家封芮靳段富焦巴牧山谷车侯全班秋仲伊宫宁仇栾甘厉祖武符刘"
    "景詹龙叶司黎薄白蒲赖卓蔺屠池乔阳党翟谭劳姬申冉雍桑牛边燕"
)


@dataclass(frozen=True)
class DetectionResult:
    textual_similarity: float
    structural_similarity: float
    entity_ratio_in_overlaps: float
    verdict: str
    reason: str
    text_a_shadow: str
    text_b_shadow: str
    ner_engines: list[str]
    overlap_blocks: list[str]


class EntityMasker:
    """NER wrapper.

    It prefers real NLP libraries:
    - English: SpaCy model if installed.
    - Chinese: jieba.posseg if installed.

    It also includes deterministic regex fallbacks so this module remains runnable
    in a minimal production container.
    """

    def __init__(self) -> None:
        self._spacy_nlp = None
        self._jieba_posseg = None
        try:
            import spacy  # type: ignore

            try:
                self._spacy_nlp = spacy.load("en_core_web_sm")
            except Exception:
                self._spacy_nlp = spacy.blank("en")
        except Exception:
            self._spacy_nlp = None

        try:
            import jieba.posseg as pseg  # type: ignore

            self._jieba_posseg = pseg
        except Exception:
            self._jieba_posseg = None

    def mask(self, text: str) -> str:
        spans = self._collect_regex_entities(text)
        spans.extend(self._collect_spacy_entities(text))
        spans.extend(self._collect_jieba_entities(text))
        merged = self._merge_spans(spans)
        return self._replace_spans(text, merged)

    def engines(self) -> list[str]:
        engines = ["regex"]
        if self._jieba_posseg:
            engines.append("jieba.posseg")
        if self._spacy_nlp and getattr(self._spacy_nlp, "pipe_names", None):
            if "ner" in self._spacy_nlp.pipe_names:
                engines.append("spacy.ner")
        return engines

    def _collect_regex_entities(self, text: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        patterns = [
            rf"[\u4e00-\u9fa5A-Za-z0-9·&（）() \-]{{2,50}}{ORG_SUFFIX_RE}",
            rf"[\u4e00-\u9fa5]{{2,14}}{LOC_SUFFIX_RE}",
            r"(?:北京|上海|天津|重庆|广州|深圳|杭州|南京|成都|武汉|西安|香港|澳门|台湾|美国|英国|日本|韩国|法国|德国|印度|新加坡|纽约|伦敦|东京|首尔)",
            r"[A-Z][A-Za-z0-9 .&-]{1,50}(?:Inc|Corp|Corporation|Ltd|LLC|Group|University|Bank|Ministry|Department)",
            r"(?:White House|United Nations|European Union|Federal Reserve|World Bank|International Monetary Fund|OpenAI|Google|Microsoft|Apple|Meta|Amazon|Tesla|Nvidia|Anthropic|DeepMind|Reuters|Bloomberg|BBC|CNN)",
            r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}",
            *POLICY_PATTERNS,
        ]
        for pattern in patterns:
            spans.extend((m.start(), m.end()) for m in re.finditer(pattern, text))

        for m in re.finditer(r"[\u4e00-\u9fa5]{2,4}(?=(?:表示|认为|指出|宣布|出席|会见|担任|创办|先生|女士|部长|书记|主任|董事长|创始人|总裁|教授|博士|院士))", text):
            value = m.group(0)
            if value[0] in ZH_SURNAMES:
                spans.append((m.start(), m.end()))
        return spans

    def _collect_spacy_entities(self, text: str) -> list[tuple[int, int]]:
        if not self._spacy_nlp:
            return []
        try:
            doc = self._spacy_nlp(text)
        except Exception:
            return []
        allowed = {"PERSON", "ORG", "GPE", "LOC", "LAW"}
        return [(ent.start_char, ent.end_char) for ent in doc.ents if ent.label_ in allowed]

    def _collect_jieba_entities(self, text: str) -> list[tuple[int, int]]:
        if not self._jieba_posseg:
            return []
        spans: list[tuple[int, int]] = []
        cursor = 0
        try:
            words = list(self._jieba_posseg.cut(text))
        except Exception:
            return []
        for word, flag in words:
            start = text.find(word, cursor)
            if start < 0:
                continue
            end = start + len(word)
            cursor = end
            if flag in {"nr", "ns", "nt", "nz"} and len(word) >= 2:
                spans.append((start, end))
        return spans

    @staticmethod
    def _merge_spans(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
        merged: list[tuple[int, int]] = []
        for start, end in sorted((s, e) for s, e in spans if e > s):
            if not merged or start > merged[-1][1]:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        return merged

    @staticmethod
    def _replace_spans(text: str, spans: list[tuple[int, int]]) -> str:
        parts: list[str] = []
        cursor = 0
        for start, end in spans:
            parts.append(text[cursor:start])
            parts.append(ENTITY_TOKEN)
            cursor = end
        parts.append(text[cursor:])
        return "".join(parts)


class PlagiarismDetector:
    def __init__(self) -> None:
        self.masker = EntityMasker()

    def analyze(self, text_a: str, text_b: str) -> DetectionResult:
        shadow_a = self.masker.mask(text_a)
        shadow_b = self.masker.mask(text_b)

        textual_similarity = self._tfidf_cosine(
            self._preprocess_for_vector(shadow_a),
            self._preprocess_for_vector(shadow_b),
        )

        blocks_a = self._structure_ngrams(shadow_a)
        blocks_b = self._structure_ngrams(shadow_b)
        hard_structural = self._jaccard(set(blocks_a), set(blocks_b))
        soft_structural = self._soft_structure_similarity(shadow_a, shadow_b)
        structural_similarity = max(hard_structural, soft_structural)
        overlap_blocks = sorted(set(blocks_a) & set(blocks_b))
        entity_ratio = self._entity_ratio(overlap_blocks)

        verdict, reason = self._judge(textual_similarity, structural_similarity, entity_ratio)
        return DetectionResult(
            textual_similarity=textual_similarity,
            structural_similarity=structural_similarity,
            entity_ratio_in_overlaps=entity_ratio,
            verdict=verdict,
            reason=reason,
            text_a_shadow=shadow_a,
            text_b_shadow=shadow_b,
            ner_engines=self.masker.engines(),
            overlap_blocks=overlap_blocks[:20],
        )

    def _preprocess_for_vector(self, text: str) -> list[str]:
        text = self._lemmatize_english(text)
        tokens: list[str] = []

        for chunk in re.findall(r"[\u4e00-\u9fa5]+", text):
            if len(chunk) == 1:
                continue
            tokens.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))
            if len(chunk) > 3:
                tokens.extend(chunk[i : i + 3] for i in range(len(chunk) - 2))

        for word in re.findall(r"[A-Za-z_]+", text.lower()):
            if len(word) > 1 and word not in EN_STOPWORDS:
                tokens.append(word)

        return [t for t in tokens if t not in ZH_STOPWORDS]

    def _structure_ngrams(self, text: str) -> list[str]:
        if self._is_mostly_english(text):
            words = self._english_structure_tokens(text)
            return [" ".join(words[i : i + 5]) for i in range(max(0, len(words) - 4))]

        skeleton_tokens = self._chinese_structure_tokens(text)
        skeleton = "".join(skeleton_tokens)
        return [skeleton[i : i + 15] for i in range(max(0, len(skeleton) - 14))]

    def _soft_structure_similarity(self, text_a: str, text_b: str) -> float:
        if self._is_mostly_english(text_a + text_b):
            tokens_a = self._english_structure_tokens(text_a)
            tokens_b = self._english_structure_tokens(text_b)
            if len(tokens_a) < 5 or len(tokens_b) < 5:
                return 0.0
            grams_a = {" ".join(tokens_a[i : i + 3]) for i in range(max(0, len(tokens_a) - 2))}
            grams_b = {" ".join(tokens_b[i : i + 3]) for i in range(max(0, len(tokens_b) - 2))}
            gram_score = self._jaccard(grams_a, grams_b)
            seq_score = SequenceMatcher(None, " ".join(tokens_a[:800]), " ".join(tokens_b[:800])).ratio()
            return max(gram_score, seq_score * 0.72)

        seq_a = "".join(self._chinese_structure_tokens(text_a))
        seq_b = "".join(self._chinese_structure_tokens(text_b))
        if len(seq_a) < 15 or len(seq_b) < 15:
            return 0.0
        grams_a = {seq_a[i : i + 8] for i in range(max(0, len(seq_a) - 7))}
        grams_b = {seq_b[i : i + 8] for i in range(max(0, len(seq_b) - 7))}
        gram_score = self._jaccard(grams_a, grams_b)
        seq_score = SequenceMatcher(None, seq_a[:3000], seq_b[:3000]).ratio()
        return max(gram_score, seq_score * 0.68)

    def _english_structure_tokens(self, text: str) -> list[str]:
        return [
            self._word_shape(self._lemmatize_english(w))
            for w in re.findall(r"\[ENTITY_REPLACED\]|[A-Za-z]+|\d+|[.,;:!?]", text)
            if w.lower() not in EN_STOPWORDS
        ]

    @staticmethod
    def _chinese_structure_tokens(text: str) -> list[str]:
        """Build a POS-like skeleton for Chinese.

        HanLP/jieba POS would be ideal in production. This deterministic
        fallback abstracts common Chinese grammar markers so synonym swaps
        still leave a comparable structure trail.
        """

        token_map = {
            ENTITY_TOKEN: "E",
            "虽然": "C",
            "尽管": "C",
            "但是": "C",
            "但": "C",
            "然而": "C",
            "仍然": "A",
            "依然": "A",
            "还是": "A",
            "正在": "A",
            "面临": "V",
            "承受": "V",
            "面对": "V",
            "决定": "V",
            "选择": "V",
            "加大": "V",
            "扩大": "V",
            "投入": "V",
            "表明": "V",
            "说明": "V",
            "显示": "V",
            "转化": "V",
            "变成": "V",
            "成为": "V",
            "举行": "V",
            "召开": "V",
            "会谈": "V",
            "会议": "N",
            "企业": "N",
            "公司": "N",
            "平台": "N",
            "技术": "N",
            "科技": "N",
            "互联网": "N",
            "监管": "N",
            "政策": "N",
            "压力": "N",
            "竞争力": "N",
            "竞争优势": "N",
            "约束": "N",
        }
        tokens: list[str] = []
        lexicon = sorted(token_map, key=len, reverse=True)
        i = 0
        while i < len(text):
            if text.startswith(ENTITY_TOKEN, i):
                tokens.append("E")
                i += len(ENTITY_TOKEN)
                continue
            ch = text[i]
            if ch in "，。、；：？！":
                tokens.append(ch)
                i += 1
                continue
            if not ("\u4e00" <= ch <= "\u9fff"):
                i += 1
                continue
            matched = None
            for word in lexicon:
                if text.startswith(word, i):
                    matched = word
                    break
            if matched:
                tokens.append(token_map[matched])
                i += len(matched)
                continue
            run = re.match(r"[\u4e00-\u9fa5]+", text[i:])
            if not run:
                i += 1
                continue
            value = run.group(0)
            for j in range(0, len(value), 2):
                piece = value[j : j + 2]
                if not piece:
                    continue
                if piece in ZH_STOPWORDS:
                    tokens.append("F")
                elif piece.endswith(("化", "成", "做", "建", "投", "增", "减", "推", "转")):
                    tokens.append("V")
                else:
                    tokens.append("N")
            i += len(value)
        return tokens

    @staticmethod
    def _word_shape(word: str) -> str:
        if word == ENTITY_TOKEN.lower() or word == ENTITY_TOKEN:
            return "ENTITY"
        if word.isdigit():
            return "NUM"
        if re.fullmatch(r"[.,;:!?]", word):
            return word
        return word.lower()

    @staticmethod
    def _is_mostly_english(text: str) -> bool:
        en = len(re.findall(r"[A-Za-z]", text))
        zh = len(re.findall(r"[\u4e00-\u9fa5]", text))
        return en > zh

    @staticmethod
    def _lemmatize_english(text: str) -> str:
        irregular = {
            "ran": "run",
            "runs": "run",
            "running": "run",
            "went": "go",
            "gone": "go",
            "goes": "go",
            "was": "be",
            "were": "be",
            "is": "be",
            "are": "be",
            "been": "be",
            "had": "have",
            "has": "have",
            "did": "do",
            "does": "do",
            "said": "say",
            "says": "say",
            "made": "make",
            "making": "make",
        }

        def lemma(match: re.Match[str]) -> str:
            word = match.group(0)
            lower = word.lower()
            if lower in irregular:
                return irregular[lower]
            if len(lower) > 5 and lower.endswith("ies"):
                return lower[:-3] + "y"
            if len(lower) > 5 and lower.endswith("ing"):
                root = lower[:-3]
                if re.search(r"([b-df-hj-np-tv-z])\1$", root):
                    root = root[:-1]
                return root
            if len(lower) > 4 and lower.endswith("ed"):
                root = lower[:-2]
                if re.search(r"([b-df-hj-np-tv-z])\1$", root):
                    root = root[:-1]
                return root
            if len(lower) > 4 and lower.endswith("es"):
                return lower[:-2]
            if len(lower) > 3 and lower.endswith("s") and not lower.endswith("ss"):
                return lower[:-1]
            return lower

        return re.sub(r"[A-Za-z]+", lemma, text)

    @staticmethod
    def _tfidf_cosine(tokens_a: list[str], tokens_b: list[str]) -> float:
        if not tokens_a or not tokens_b:
            return 0.0
        docs = [tokens_a, tokens_b]
        vocab = sorted(set(tokens_a) | set(tokens_b))
        vectors: list[list[float]] = []
        for tokens in docs:
            tf = Counter(tokens)
            vector = []
            for term in vocab:
                df = int(term in docs[0]) + int(term in docs[1])
                idf = math.log((1 + len(docs)) / (1 + df)) + 1
                vector.append((tf[term] / len(tokens)) * idf)
            vectors.append(vector)
        return PlagiarismDetector._cosine(vectors[0], vectors[1])

    @staticmethod
    def _cosine(vec_a: list[float], vec_b: list[float]) -> float:
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

    @staticmethod
    def _jaccard(set_a: set[str], set_b: set[str]) -> float:
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    @staticmethod
    def _entity_ratio(blocks: list[str]) -> float:
        if not blocks:
            return 0.0
        joined = " ".join(blocks)
        return joined.count(ENTITY_TOKEN) * len(ENTITY_TOKEN) / max(len(joined), 1)

    @staticmethod
    def _judge(textual: float, structural: float, entity_ratio: float) -> tuple[str, str]:
        if textual >= 0.20 and structural < 0.30:
            return "🟡 拦截警告", "文字相似度达到 20% 阈值，虽语言结构未达线，仍建议按疑似抄袭复核。"
        if structural < 0.30:
            return "🟢 安全放行", "语言结构相似度低于 30%，属于独立原创或正常引用。"
        if 0.30 <= structural <= 0.45 and textual < 0.25:
            if entity_ratio > 0.35:
                return "🟢 安全放行", "结构重合主要来自专有实体，倾向客观时政/商务报道。"
            return "🟡 拦截警告", "字面相似度低但结构重合高，且非实体占比高，存在深度洗稿与框架抄袭嫌疑。"
        if structural > 0.45:
            return "🔴 严重违规", "语言结构相似度超过 45%，高度疑似恶意搬运或全篇洗稿。"
        if textual >= 0.20:
            return "🟡 拦截警告", "全文词汇重合度较高，建议人工复核。"
        return "🟢 安全放行", "未命中高风险阈值。"


def _print_report(title: str, result: DetectionResult) -> None:
    print(f"\n====== {title} ======")
    print(f"全文相似度: {result.textual_similarity:.2%}")
    print(f"语言结构相似度: {result.structural_similarity:.2%}")
    print(f"重合结构中的实体占比: {result.entity_ratio_in_overlaps:.2%}")
    print(f"判定: {result.verdict}")
    print(f"原因: {result.reason}")
    print(f"NER 引擎: {', '.join(result.ner_engines)}")
    print("影子文本 A:", result.text_a_shadow[:180], "...")
    print("影子文本 B:", result.text_b_shadow[:180], "...")
    print("重合结构样例:", result.overlap_blocks[:3])


if __name__ == "__main__":
    detector = PlagiarismDetector()

    zh_a = """
    字节跳动创始人张一鸣与生态环境部黄部长在北京市朝阳区举行闭门会谈。
    虽然平台企业面临监管压力，但张一鸣依然决定加大绿色算力投入。
    这一决定表明，技术公司正在把合规压力转化为长期竞争力。
    """
    zh_b = """
    阿里巴巴董事长蔡崇信与商务部李主任在上海市浦东新区召开内部会议。
    虽然互联网企业承受政策压力，但蔡崇信仍然选择扩大低碳计算投入。
    这说明科技企业正在把外部约束转化为未来竞争优势。
    """
    _print_report("中文洗稿检测样例", detector.analyze(zh_a, zh_b))

    en_a = """
    Elon Musk met officials from the White House in Washington.
    Although Tesla faces political pressure, Musk is still running a long-term investment plan.
    The decision shows that technology companies are turning regulatory pressure into strategic advantage.
    """
    en_b = """
    Sam Altman met leaders from the Federal Reserve in New York.
    Although OpenAI faces policy pressure, Altman still runs a long-term deployment plan.
    The move suggests that AI companies are turning regulatory pressure into strategic advantage.
    """
    _print_report("English plagiarism check sample", detector.analyze(en_a, en_b))
