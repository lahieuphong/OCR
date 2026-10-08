"""Synthetic text lines in the style of Vietnamese administrative documents.

Lines are assembled from the vocabulary in ``lexicon/administrative.txt`` with
random structure, numbers, dates and document identifiers. Nothing is copied
from a real document.

Body text is produced the way a recognizer meets it: a paragraph of several
sentences is wrapped to a line width and one of the resulting lines is kept.
Such a line usually starts or ends in the middle of a sentence, like the crop
of one line of a real page.

Everything is driven by an explicit seed: the same seed and index always give
the same line.
"""

from __future__ import annotations

import random
import re
import textwrap
import unicodedata
from dataclasses import dataclass
from pathlib import Path

LEXICON_FILE = Path(__file__).resolve().parent / "lexicon" / "administrative.txt"
# VietOCR decodes at most 128 tokens; a longer label could never be reproduced.
MAX_CHARACTERS = 120
NORMAL_WIDTHS = (34, 74)  # characters per line when wrapping ordinary text
LONG_WIDTHS = (84, 118)
LONG_MIN_CHARACTERS = 76

# Relative frequency of each kind of line.
KINDS = {
    "body": 46,
    "legal_basis": 8,
    "heading": 9,
    "document_number": 6,
    "date_place": 5,
    "recipient": 6,
    "signature": 5,
    "article": 6,
    "contact": 4,
    "figures": 5,
}
ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")


@dataclass(frozen=True)
class Line:
    text: str
    kind: str


class Lexicon:
    """The sections of the vocabulary file, each a list of entries."""

    def __init__(self, path: Path = LEXICON_FILE) -> None:
        self.sections: dict[str, list[str]] = {}
        current = None
        for raw in path.read_text(encoding="utf-8").splitlines():
            entry = unicodedata.normalize("NFC", raw.strip())
            if not entry or entry.startswith("#"):
                continue
            if entry.startswith("[") and entry.endswith("]"):
                current = self.sections.setdefault(entry[1:-1], [])
            elif current is None:
                raise ValueError(f"{path}: entry before the first section: {entry!r}")
            else:
                current.append(entry)

    def __getitem__(self, section: str) -> list[str]:
        return self.sections[section]

    def entries(self) -> list[str]:
        return [entry for section in self.sections.values() for entry in section]


def capitalise(text: str) -> str:
    return text[:1].upper() + text[1:]


def hard_case_pattern(phrase: str) -> str:
    """A regular expression for ``phrase`` as whole words.

    A word boundary is required only on a side where the phrase ends in a
    letter or digit, so that ``@`` is found inside an address and ``.vn`` at
    the end of one.
    """
    before = r"(?<!\w)" if phrase[:1].isalnum() else ""
    after = r"(?!\w)" if phrase[-1:].isalnum() else ""
    return before + re.escape(phrase) + after


def load_hard_cases(path: Path) -> list[str]:
    """Entries of a hard-case file; ``#`` starts a comment, order is kept."""
    entries = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        entry = unicodedata.normalize("NFC", raw.split("#", 1)[0].strip("\n"))
        # "- " is a hard case: keep inner and trailing spaces, drop empty lines.
        if entry.strip() and entry not in entries:
            entries.append(entry if entry.endswith(" ") and entry.strip() == "-" else entry.strip())
    return entries


class TextGenerator:
    """Lines of administrative text, restricted to an allowed character set."""

    def __init__(
        self,
        lexicon: Lexicon,
        allowed_characters: str,
        banned_texts: frozenset[str] = frozenset(),
    ) -> None:
        self.lexicon = lexicon
        self.allowed = set(allowed_characters)
        # Texts that must never be produced: the lines of the frozen test set.
        self.banned = banned_texts

    # --- small pieces ----------------------------------------------------------

    def pick(self, rng: random.Random, section: str) -> str:
        return rng.choice(self.lexicon[section])

    def year(self, rng: random.Random) -> int:
        return rng.randint(2015, 2030)

    def date(self, rng: random.Random) -> str:
        day, month = rng.randint(1, 28), rng.randint(1, 12)
        # Official style pads the day below 10 and the months January and February.
        if rng.random() < 0.6:
            day_text = f"{day:02d}"
            month_text = f"{month:02d}" if month < 3 else str(month)
        else:
            day_text, month_text = str(day), str(month)
        return f"ngày {day_text} tháng {month_text} năm {self.year(rng)}"

    def short_date(self, rng: random.Random) -> str:
        return f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{self.year(rng)}"

    def document_code(self, rng: random.Random) -> str:
        """A document identifier such as ``15/2024/NĐ-CP`` or ``57-NQ/TW``."""
        number, year = rng.randint(1, 2999), self.year(rng)
        abbreviation = self.pick(rng, "document_type").split("|")[1]
        issuer = self.pick(rng, "issuer")
        style = rng.random()
        if style < 0.35:
            return f"{number}/{year}/{abbreviation}-{issuer}"
        if style < 0.70:
            return f"{number}/{abbreviation}-{issuer}"
        if style < 0.82:
            return f"{number}-{rng.choice(('KL', 'NQ', 'CT', 'QĐ', 'TB', 'HD'))}/TW"
        if style < 0.92:
            return f"{number}/{issuer}-{self.pick(rng, 'issuer')}"
        return f"{number}/{year}/{rng.choice(('QH15', 'QH14', 'UBTVQH15'))}"

    def amount(self, rng: random.Random) -> str:
        value = rng.choice((rng.randint(1, 999), rng.randint(1000, 999_999), rng.randint(10**6, 10**9)))
        text = f"{value:,}".replace(",", ".")
        if rng.random() < 0.25:
            text += f",{rng.randint(1, 99)}"
        return f"{text} {self.pick(rng, 'measure')}"

    def percentage(self, rng: random.Random) -> str:
        whole = rng.randint(0, 99)
        return f"{whole},{rng.randint(1, 99)}%" if rng.random() < 0.5 else f"{whole}%"

    def person(self, rng: random.Random) -> str:
        parts = [self.pick(rng, "surname"), self.pick(rng, "middle_name"), self.pick(rng, "given_name")]
        if rng.random() < 0.25:
            parts.insert(2, self.pick(rng, "middle_name"))
        return " ".join(parts)

    def place(self, rng: random.Random) -> str:
        """A province-level unit with its level: ``tỉnh Nghệ An``, ``thành phố Huế``."""
        province = self.pick(rng, "province")
        if province.startswith("Thành phố"):
            return province
        centrally_run = ("Hà Nội", "Hải Phòng", "Đà Nẵng", "Cần Thơ", "Huế")
        return f"{'thành phố' if province in centrally_run else 'tỉnh'} {province}"

    def local_body(self, rng: random.Random) -> str:
        place = self.place(rng)
        style = rng.random()
        if style < 0.5:
            return f"Ủy ban nhân dân {place}"
        if style < 0.65:
            return f"Hội đồng nhân dân {place}"
        return f"{self.pick(rng, 'department').replace(' tỉnh', '')} {place}"

    def body(self, rng: random.Random) -> str:
        """Any state body: central, local, or a unit of a ministry."""
        style = rng.random()
        if style < 0.5:
            return self.pick(rng, "agency")
        if style < 0.8:
            return self.local_body(rng)
        return f"{self.pick(rng, 'unit')}, {self.pick(rng, 'agency')}"

    def topic(self, rng: random.Random) -> str:
        topic = self.pick(rng, "object")
        style = rng.random()
        if style < 0.2:
            topic += f" năm {self.year(rng)}"
        elif style < 0.35:
            start = self.year(rng)
            topic += f" giai đoạn {start} - {start + rng.choice((3, 4, 5, 10))}"
        elif style < 0.45:
            topic += f" trên địa bàn {self.place(rng)}"
        return topic

    # --- sentences -------------------------------------------------------------

    def sentence(self, rng: random.Random) -> str:
        """One sentence. Built in its natural case, then capitalised if it opens the sentence."""
        style = rng.random()
        if style < 0.30:
            subject = rng.choice((self.pick(rng, "subject"), self.body(rng)))
            text = f"{subject} {self.pick(rng, 'action')} {self.topic(rng)} {self.pick(rng, 'tail')}"
            if rng.random() < 0.35:
                text += f"; {self.pick(rng, 'action')} {self.topic(rng)}"
        elif style < 0.45:
            deadline = rng.choice(
                (
                    f"trước {self.date(rng)}",
                    f"trong quý {rng.choice(ROMAN[:4])} năm {self.year(rng)}",
                    f"trong tháng {rng.randint(1, 12)} năm {self.year(rng)}",
                )
            )
            text = (
                f"giao {self.body(rng)} chủ trì, phối hợp với {self.body(rng)} "
                f"{self.pick(rng, 'action')} {self.topic(rng)}, báo cáo {self.pick(rng, 'agency')} {deadline}"
            )
        elif style < 0.60:
            text = f"{self.topic(rng)} {self.pick(rng, 'evaluation')}"
            if rng.random() < 0.5:
                text += f", {self.pick(rng, 'tail')}"
        elif style < 0.72:
            trend = rng.choice(("tăng", "giảm", "đạt", "bằng", "vượt"))
            reference = rng.choice(("cùng kỳ năm trước", "kế hoạch được giao", f"năm {self.year(rng)}"))
            text = (
                f"{self.topic(rng)} đạt {self.amount(rng)}, {trend} {self.percentage(rng)} so với {reference}"
            )
        elif style < 0.86:
            kind = self.pick(rng, "document_type").split("|")[0].capitalize()
            text = (
                f"thực hiện {kind} số {self.document_code(rng)} {self.date(rng)} của {self.body(rng)} "
                f"về {self.topic(rng)}, {self.pick(rng, 'subject')} {self.pick(rng, 'action')} {self.topic(rng)}"
            )
        elif style < 0.93:
            kind = self.pick(rng, "document_type").split("|")[0].capitalize()
            text = rng.choice(
                (
                    f"{kind} này có hiệu lực thi hành kể từ {self.date(rng)}",
                    f"{kind} này có hiệu lực kể từ ngày ký ban hành",
                    f"{self.pick(rng, 'position')}, {self.pick(rng, 'position')} và "
                    f"{self.pick(rng, 'subject')} chịu trách nhiệm thi hành {kind} này",
                )
            )
        elif style < 0.97:
            text = (
                f"{rng.choice(('ông', 'bà', 'đồng chí'))} {self.person(rng)}, {self.pick(rng, 'position')} "
                f"{self.body(rng)}, {self.pick(rng, 'action')} {self.topic(rng)}"
            )
        else:
            numerals = ("(i)", "(ii)", "(iii)", "(iv)")[: rng.randint(2, 4)]
            items = "; ".join(f"{mark} {self.pick(rng, 'action')} {self.topic(rng)}" for mark in numerals)
            text = f"{self.pick(rng, 'subject')} tập trung vào các nhiệm vụ: {items}"
        if rng.random() < 0.08:
            text += f' theo phương châm "{self.pick(rng, "slogan")}"'
        opening = f"{self.pick(rng, 'connector')} {text}" if rng.random() < 0.3 else capitalise(text)
        return opening + rng.choice((".", ".", ".", ".", ";", ";", "./."))

    def paragraph(self, rng: random.Random) -> str:
        sentences = [self.sentence(rng) for _ in range(rng.randint(2, 4))]
        prefix = rng.random()
        if prefix < 0.12:
            sentences[0] = f"{rng.randint(1, 15)}. {sentences[0]}"
        elif prefix < 0.22:
            sentences[0] = f"{rng.choice('abcdeghik')}) {sentences[0]}"
        elif prefix < 0.30:
            sentences[0] = f"- {sentences[0]}"
        return " ".join(sentences)

    def wrapped_line(self, rng: random.Random, text: str, widths: tuple[int, int], minimum: int = 1) -> str:
        """One line of ``text`` wrapped to a random width; never a cut-off line."""
        lines = textwrap.wrap(
            text, width=rng.randint(*widths), break_long_words=False, break_on_hyphens=False
        )
        usable = [line for line in lines if minimum <= len(line) <= MAX_CHARACTERS]
        return rng.choice(usable) if usable else ""

    # --- one line of each kind -------------------------------------------------

    def body_line(self, rng: random.Random, long: bool = False) -> str:
        if long:
            return self.wrapped_line(rng, self.paragraph(rng), LONG_WIDTHS, LONG_MIN_CHARACTERS)
        return self.wrapped_line(rng, self.paragraph(rng), NORMAL_WIDTHS)

    def legal_basis_line(self, rng: random.Random) -> str:
        style = rng.random()
        if style < 0.35:
            text = f"Căn cứ {self.pick(rng, 'law')} {self.date(rng)};"
        elif style < 0.50:
            text = f"Căn cứ {self.pick(rng, 'law')} số {rng.randint(1, 99)}/{self.year(rng)}/QH15;"
        elif style < 0.70:
            text = (
                f"Căn cứ Nghị định số {rng.randint(1, 200)}/{self.year(rng)}/NĐ-CP {self.date(rng)} của Chính phủ "
                f"quy định chức năng, nhiệm vụ, quyền hạn và cơ cấu tổ chức của {self.pick(rng, 'agency')};"
            )
        elif style < 0.85:
            text = f"Theo đề nghị của {self.pick(rng, 'position')} {self.pick(rng, 'unit')}."
        else:
            text = (
                f"Xét đề nghị của {self.pick(rng, 'position')} {self.body(rng)} tại Tờ trình số "
                f"{self.document_code(rng)} {self.date(rng)},"
            )
        return self.wrapped_line(rng, text, (40, 80))

    def heading_line(self, rng: random.Random) -> str:
        style = rng.random()
        if style < 0.18:
            return self.pick(rng, "document_type").split("|")[0] + rng.choice(("", "", ":"))
        if style < 0.26:
            return rng.choice(("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", "Độc lập - Tự do - Hạnh phúc"))
        if style < 0.48:
            return self.body(rng).upper()
        if style < 0.72:
            title = f"Về việc {self.pick(rng, 'action')} {self.topic(rng)}"
            title = self.wrapped_line(rng, title, (30, 70))
            return title.upper() if rng.random() < 0.6 else title
        if style < 0.84:
            return f"Chương {rng.choice(ROMAN)}"
        if style < 0.92:
            return self.wrapped_line(rng, self.topic(rng).upper(), (24, 60))
        return f"Mục {rng.randint(1, 9)}. {self.pick(rng, 'article_title').upper()}"

    def document_number_line(self, rng: random.Random) -> str:
        style = rng.random()
        if style < 0.55:
            return f"Số: {self.document_code(rng)}"
        if style < 0.70:
            return f"Số {self.document_code(rng)}"
        title = f"V/v {self.pick(rng, 'action')} {self.topic(rng)}"
        return self.wrapped_line(rng, title, (28, 60))

    def date_place_line(self, rng: random.Random) -> str:
        style = rng.random()
        if style < 0.7:
            place = self.pick(rng, "province").replace("Thành phố ", "TP. " if rng.random() < 0.5 else "Thành phố ")
            return f"{place}, {self.date(rng)}"
        if style < 0.85:
            return f"Thời gian ký: {self.timestamp(rng)}"
        return f"{capitalise(self.date(rng))}"

    def timestamp(self, rng: random.Random) -> str:
        return (
            f"{rng.randint(1, 28):02d}.{rng.randint(1, 12):02d}.{self.year(rng)} "
            f"{rng.randint(7, 18):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d} +07:00"
        )

    def recipient_line(self, rng: random.Random) -> str:
        style = rng.random()
        if style < 0.10:
            return "Nơi nhận:"
        if style < 0.25:
            copies = f" ({rng.randint(1, 30)}{rng.choice(('b', ''))})" if rng.random() < 0.6 else ""
            return f"- Lưu: VT, {self.pick(rng, 'issuer')}{copies}."
        if style < 0.40:
            return f"- {self.body(rng)};"
        recipient = self.pick(rng, "recipient").replace("{article}", str(rng.randint(1, 9)))
        return f"- {recipient};"

    def signature_line(self, rng: random.Random) -> str:
        style = rng.random()
        if style < 0.45:
            first, second = self.pick(rng, "signer").split("|")
            return rng.choice([part for part in (first, second) if part])
        if style < 0.85:
            return self.person(rng)
        return rng.choice(("(Đã ký)", "(Ký, ghi rõ họ tên và đóng dấu)", "(Ký tên, đóng dấu)", "Người lập biểu"))

    def article_line(self, rng: random.Random) -> str:
        number = rng.randint(1, 60)
        if rng.random() < 0.5:
            return f"Điều {number}. {self.pick(rng, 'article_title')}"
        text = f"Điều {number}. {capitalise(self.pick(rng, 'action'))} {self.topic(rng)}"
        return self.wrapped_line(rng, text, (36, 76))

    def contact_line(self, rng: random.Random) -> str:
        style = rng.random()
        if style < 0.30:
            return f"Người ký: {self.body(rng).upper()}"
        if style < 0.50:
            return f"Cơ quan: {self.body(rng).upper()}"
        domain = self.pick(rng, "email_domain")
        if style < 0.72:
            return f"Email: {self.pick(rng, 'mailbox')}@{domain}"
        if style < 0.86:
            return f"Website: {rng.choice(('https://', 'http://', ''))}{rng.choice(('www.', ''))}{domain}"
        area = rng.choice(("024", "028", "0236", "0225", "0292"))
        return f"Điện thoại: {area}.{rng.randint(1000, 9999)}.{rng.randint(1000, 9999)}; Fax: {area}.{rng.randint(1000, 9999)}.{rng.randint(1000, 9999)}"

    def figures_line(self, rng: random.Random) -> str:
        style = rng.random()
        if style < 0.35:
            text = (
                f"{capitalise(self.topic(rng))}: {self.amount(rng)}, trong đó {self.amount(rng)} "
                f"({self.percentage(rng)}) từ ngân sách trung ương"
            )
        elif style < 0.55:
            text = f"Mã số thuế: {rng.randint(10**9, 10**10 - 1)}; Số tài khoản: {rng.randint(10**11, 10**13 - 1)}"
        elif style < 0.75:
            text = (
                f"Từ ngày {self.short_date(rng)} đến ngày {self.short_date(rng)}, mức thu là "
                f"{self.amount(rng)}, tăng từ {self.percentage(rng)} lên {self.percentage(rng)}"
            )
        else:
            text = (
                f"{self.pick(rng, 'document_type').split('|')[0].capitalize()} số {self.document_code(rng)} "
                f"và số {self.document_code(rng)} {self.date(rng)}"
            )
        return self.wrapped_line(rng, text, (40, 78))

    # --- public API --------------------------------------------------------------

    def acceptable(self, text: str) -> bool:
        return (
            0 < len(text) <= MAX_CHARACTERS
            and text == text.strip()
            and "  " not in text
            and text not in self.banned
            and set(text) <= self.allowed
            and unicodedata.is_normalized("NFC", text)
        )

    def line(self, rng: random.Random, kind: str | None = None, long: bool = False) -> Line:
        """One acceptable line. ``long`` asks for a long body line."""
        for _ in range(200):
            chosen = "body" if long else kind or rng.choices(list(KINDS), weights=list(KINDS.values()))[0]
            text = self.body_line(rng, long=True) if long else getattr(self, f"{chosen}_line")(rng)
            if self.acceptable(text) and (not long or len(text) >= LONG_MIN_CHARACTERS):
                return Line(text, chosen)
        raise RuntimeError("could not generate an acceptable line; check the lexicon")

    def hard_case_line(self, rng: random.Random, phrase: str, avoid: frozenset[str] | set[str] = frozenset()) -> Line:
        """A line that contains ``phrase`` as whole words, in whatever case.

        Lines are drawn from the ordinary generator until one contains the
        phrase, so it appears in the contexts it really occurs in. Lines in
        ``avoid`` are passed over. A phrase the vocabulary cannot produce (any
        more) is placed in front of an ordinary line.
        """
        pattern = re.compile(hard_case_pattern(phrase), re.IGNORECASE)
        for _ in range(3000):
            text = self.line(rng).text
            if not pattern.search(text) or text in avoid:
                continue
            # A fifth of the hits in capitals: headings are where stacked marks are
            # hardest. Only for words; an address or a numeral keeps its case.
            if phrase.replace(" ", "").isalpha() and rng.random() < 0.2:
                text = text.upper()
            if self.acceptable(text):
                return Line(text, "hard_case")
        for _ in range(200):
            form = rng.random()
            variant = phrase if form < 0.5 else capitalise(phrase) if form < 0.8 else phrase.upper()
            text = f"{variant}, {self.line(rng, 'body').text}"
            if self.acceptable(text) and text not in avoid:
                return Line(text, "hard_case")
        raise RuntimeError(f"could not place the hard case {phrase!r}")

    def coverage_line(self, rng: random.Random, letter: str) -> Line:
        """A line that contains ``letter``, built from vocabulary entries that have it."""
        entries = [entry for entry in self.lexicon.entries() if letter.lower() in entry.lower() and "|" not in entry and "{" not in entry]
        if not entries:
            raise RuntimeError(f"no vocabulary entry contains {letter!r}")
        for _ in range(200):
            chosen = [rng.choice(entries)] + [rng.choice(self.lexicon.entries()) for _ in range(rng.randint(1, 3))]
            chosen = [entry for entry in chosen if "|" not in entry and "{" not in entry]
            rng.shuffle(chosen)
            text = rng.choice((", ".join(chosen), " và ".join(chosen[:2]), f"{chosen[0]}: {', '.join(chosen[1:])}"))
            # An upper-case letter is only reached by writing the line in capitals.
            text = text.upper() if letter.isupper() else text
            if letter in text and self.acceptable(text):
                return Line(text, "coverage")
        raise RuntimeError(f"could not build a line with {letter!r}")
