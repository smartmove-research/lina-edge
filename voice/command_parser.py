# voice/command_parser.py

class CommandParser:
    """
    Stub for parsing freeform text into (command, params).
    Replace `parse` with an LLM or regex-based logic.
    """
    async def parse(self, text: str) -> (str, dict):
        # VERY naive: split on space
        tokens = text.lower().split()
        cmd = tokens[0]
        params = {'args': tokens[1:]}
        return cmd, params