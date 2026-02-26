using System.Collections.Generic;
using System.IO;

namespace PromptTool.Core.Models
{
    public enum WildcardSourceType
    {
        Json,
        PlainText
    }

    public class WildcardDefinition
    {
        public string Name { get; set; }
        public string FilePath { get; set; }
        public WildcardSourceType SourceType { get; set; }
        public List<string> Values { get; set; } = new List<string>();

        public WildcardDefinition(string name, string filePath, WildcardSourceType sourceType, List<string> values)
        {
            Name = name;
            FilePath = filePath;
            SourceType = sourceType;
            Values = values;
        }

        public WildcardDefinition(string name, string filePath, WildcardSourceType sourceType)
        {
            Name = name;
            FilePath = filePath;
            SourceType = sourceType;
        }

        public string GetRandomValue()
        {
            if (Values == null || Values.Count == 0)
            {
                return Name; // Return the wildcard name itself if no values are loaded
            }
            return Values[new System.Random().Next(Values.Count)];
        }
    }
}