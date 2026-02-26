namespace PromptTool.ViewModels;

public record DependencyInfo(string Name, int References, string[] Includes, string[] RequiredBy);
