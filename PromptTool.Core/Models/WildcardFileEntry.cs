namespace PromptTool.Core.Models
{
    public class WildcardFileEntry
    {
        public string Name { get; set; }
        public string FilePath { get; set; }
        public string? Content { get; set; } // Optional: to hold file content if needed
        public bool IsArchived { get; set; }

        public WildcardFileEntry(string name, string filePath, string? content = null, bool isArchived = false)
        {
            Name = name;
            FilePath = filePath;
            Content = content;
            IsArchived = isArchived;
        }
    }
}
