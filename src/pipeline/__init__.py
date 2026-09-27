"""Server-side orchestration of the offer pipeline.

Deliberately EMPTY of re-exports. `controllers.JobController` needs
`pipeline.progress` and `pipeline.stages`, while `pipeline.node.*` needs the
controllers - so eagerly importing the graph here made `import controllers`
re-enter itself through `pipeline`, and a partially-initialised `controllers`
package silently handed out the `ParseController` MODULE where the class was
meant (the package and the module share a name, so the attribute lookup falls
back to the submodule instead of raising). That failed at runtime as
"'module' object is not callable", nowhere near the import that caused it.

Import the submodule you actually want:

    from pipeline import runner
    from pipeline.progress import JobProgress
    from pipeline.stages import stages_for
"""
