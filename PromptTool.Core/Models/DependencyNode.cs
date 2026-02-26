using System.Collections.Generic;

namespace PromptTool.Core.Models;

public class DependencyNode
{
    public DependencyNode(string name)
    {
        Name = name;
    }

    public string Name { get; }
    public List<string> Includes { get; } = new();
    public List<string> RequiredBy { get; } = new();
}
