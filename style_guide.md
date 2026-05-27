# Corporate Engineering Guidelines

## Rule 1: SQL Database Security
Never use direct Python string formatting or variable concatenation (like f-strings) when writing SQL strings. Always utilize parameterized query formats to prevent critical SQL injection flaws.

## Rule 2: Naming Convention
All Python functional names and local variables must strictly follow snake_case syntax guidelines. Never use camelCase formatting profiles.