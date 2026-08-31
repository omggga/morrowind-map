"""Isolated Original GOTY HD renderer entrypoints.

The package reuses the frozen OpenMW rendering mechanics in a separate Python
process while replacing every dataset/profile constant before those modules
are imported.  Importing this package alone never mutates the Poison producer.
"""
