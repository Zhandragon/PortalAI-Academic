"""Literal, case-insensitive search over saved record summaries only."""


def matches(query, *values):
    terms = str(query or '').casefold().split()
    text = ' '.join(' '.join(str(value or '').casefold().split()) for value in values)
    return all(term in text for term in terms)
