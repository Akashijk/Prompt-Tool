namespace PromptTool.ViewModels;

public enum FillMissingOutcome
{
    Updated,
    NoChanges,
    Canceled,
    PreconditionFailed
}

public readonly record struct FillMissingResult(FillMissingOutcome Outcome, string Message)
{
    public static FillMissingResult Updated(string message) => new(FillMissingOutcome.Updated, message);
    public static FillMissingResult NoChanges(string message) => new(FillMissingOutcome.NoChanges, message);
    public static FillMissingResult Canceled(string message) => new(FillMissingOutcome.Canceled, message);
    public static FillMissingResult PreconditionFailed(string message) => new(FillMissingOutcome.PreconditionFailed, message);
}
