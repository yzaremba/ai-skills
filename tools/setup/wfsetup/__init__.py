"""The workflow setup tool: settings now, installation later.

Modules:
    cli         argument parsing and the one place errors are printed
    commands    one module per command, found by name
    dictionary  a provider's dictionary: models, efforts, versions, the list
    errors      the error a user can act on, and the exit codes
    locations   the clone, the user home and the project of a run
    paths       what is at a path, asked without a traceback
    profiles    the model and effort a role definition runs with
    roles       a role's source, role.toml
    schema      what a settings file may hold
    settings    the layers, and the effective value of each key
    tomlio      reading and writing TOML
"""
