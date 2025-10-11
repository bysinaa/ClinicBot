def is_valid_iran_national_id(code: str) -> bool:
    """
    Validate Iranian National ID (کدملی) by checksum.
    Accepts strings of length 10 (leading zeros allowed).
    """
    if not code or not code.isdigit():
        return False
    code = code.zfill(10)
    if len(code) != 10:
        return False
    if code == code[0] * 10:
        return False
    checksum = int(code[9])
    s = sum(int(code[i]) * (10 - i) for i in range(9))
    r = s % 11
    return (r < 2 and checksum == r) or (r >= 2 and checksum == 11 - r)
