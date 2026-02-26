using System.Text.Json.Serialization;
using System.Collections.Generic;

namespace PromptTool.Core.Clients.InvokeAI;

// Main model definition
public record InvokeAIModel
{
    [JsonPropertyName("name")]
    public string Name { get; init; } = "";

    [JsonPropertyName("base")]
    public string Base { get; init; } = "";

    [JsonPropertyName("type")]
    public string Type { get; init; } = "";

    [JsonPropertyName("format")]
    public string Format { get; init; } = "";
    
    [JsonPropertyName("key")]
    public string Key { get; init; } = "";
    
    [JsonPropertyName("hash")]
    public string Hash { get; init; } = "";
    
    [JsonPropertyName("submodels")]
    public List<InvokeAISubmodel>? Submodels { get; init; }
}

public record InvokeAISubmodel
{
    [JsonPropertyName("type")]
    public string Type { get; init; } = "";
}

// Graph and Node structures for building generation requests
public record InvokeAIGraph
{
    [JsonPropertyName("nodes")]
    public Dictionary<string, IInvokeAINode> Nodes { get; init; } = new();

    [JsonPropertyName("edges")]
    public List<InvokeAIEdge> Edges { get; init; } = new();
}

[JsonDerivedType(typeof(MainModelLoaderNode), typeDiscriminator: "main_model_loader")]
[JsonDerivedType(typeof(VaeLoaderNode), typeDiscriminator: "vae_loader")]
[JsonDerivedType(typeof(LoraLoaderNode), typeDiscriminator: "lora_loader")]
[JsonDerivedType(typeof(CompelNode), typeDiscriminator: "compel")]
[JsonDerivedType(typeof(StringNode), typeDiscriminator: "string")]
[JsonDerivedType(typeof(NoiseNode), typeDiscriminator: "noise")]
[JsonDerivedType(typeof(DenoiseLatentsNode), typeDiscriminator: "denoise_latents")]
[JsonDerivedType(typeof(LatentsToImageNode), typeDiscriminator: "l2i")]
[JsonDerivedType(typeof(SaveImageNode), typeDiscriminator: "save_image")]
[JsonDerivedType(typeof(SdxlModelLoaderNode), typeDiscriminator: "sdxl_model_loader")]
[JsonDerivedType(typeof(SdxlLoraLoaderNode), typeDiscriminator: "sdxl_lora_loader")]
[JsonDerivedType(typeof(SdxlCompelPromptNode), typeDiscriminator: "sdxl_compel_prompt")]
[JsonDerivedType(typeof(SpandrelImageToImageAutoscaleNode), typeDiscriminator: "spandrel_image_to_image_autoscale")]
public interface IInvokeAINode
{
    [JsonPropertyName("id")]
    string Id { get; init; }

    [JsonPropertyName("type")]
    string Type { get; init; }
}

public record InvokeAIEdge
{
    [JsonPropertyName("source")]
    public required EdgePoint Source { get; init; }

    [JsonPropertyName("destination")]
    public required EdgePoint Destination { get; init; }
}

public record EdgePoint
{
    [JsonPropertyName("node_id")]
    public string NodeId { get; init; } = "";

    [JsonPropertyName("field")]
    public string Field { get; init; } = "";
}

// Specific Node type implementations
public record MainModelLoaderNode : IInvokeAINode
{
    public string Id { get; init; } = "main_model_loader";
    public string Type { get; init; } = "main_model_loader";
    [JsonPropertyName("model")]
    public InvokeAIModel Model { get; init; } = new();
}

public record VaeLoaderNode : IInvokeAINode
{
    public string Id { get; init; } = "vae_loader";
    public string Type { get; init; } = "vae_loader";
    [JsonPropertyName("vae_model")]
    public InvokeAIModel VaeModel { get; init; } = new();
}


public record LoraLoaderNode : IInvokeAINode
{
    public string Id { get; init; } = "";
    public string Type { get; init; } = "lora_loader";
    [JsonPropertyName("lora")]
    public InvokeAIModel Lora { get; init; } = new();
    [JsonPropertyName("weight")]
    public double Weight { get; init; }
}

public record CompelNode : IInvokeAINode
{
    public string Id { get; init; } = "";
    public string Type { get; init; } = "compel";
}

public record StringNode : IInvokeAINode
{
    public string Id { get; init; } = "";
    public string Type { get; init; } = "string";
    [JsonPropertyName("value")]
    public string Value { get; init; } = "";
}

public record NoiseNode : IInvokeAINode
{
    public string Id { get; init; } = "noise";
    public string Type { get; init; } = "noise";
    [JsonPropertyName("seed")]
    public int Seed { get; init; }
    [JsonPropertyName("width")]
    public int Width { get; init; }
    [JsonPropertyName("height")]
    public int Height { get; init; }
    [JsonPropertyName("use_cpu")]
    public bool UseCpu { get; init; } = false;
}

public record DenoiseLatentsNode : IInvokeAINode
{
    public string Id { get; init; } = "denoise_latents";
    public string Type { get; init; } = "denoise_latents";
    [JsonPropertyName("steps")]
    public int Steps { get; init; }
    [JsonPropertyName("cfg_scale")]
    public double CfgScale { get; init; }
    [JsonPropertyName("scheduler")]
    public string Scheduler { get; init; } = "";
    [JsonPropertyName("denoising_start")]
    public double DenoisingStart { get; init; } = 0.0;
    [JsonPropertyName("denoising_end")]
    public double DenoisingEnd { get; init; } = 1.0;
    [JsonPropertyName("cfg_rescale_multiplier")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)]
    public double CfgRescaleMultiplier { get; init; } = 0.0;
}

public record LatentsToImageNode : IInvokeAINode
{
    public string Id { get; init; } = "l2i";
    public string Type { get; init; } = "l2i";
    [JsonPropertyName("is_intermediate")]
    public bool IsIntermediate { get; init; } = false;
    [JsonPropertyName("use_cache")]
    public bool UseCache { get; init; } = false;
    [JsonPropertyName("save_to_gallery")]
    public bool SaveToGallery { get; init; }
    [JsonPropertyName("image_category")]
    public string ImageCategory { get; init; } = "general";
    [JsonPropertyName("fp32")]
    public bool Fp32 { get; init; } = true;
}

public record SaveImageNode : IInvokeAINode
{
    public string Id { get; init; } = "save_image";
    public string Type { get; init; } = "save_image";
    [JsonPropertyName("image")]
    public InvokeAIImageField? Image { get; init; }
    [JsonPropertyName("is_intermediate")]
    public bool IsIntermediate { get; init; }
}

// SDXL Specific Nodes
public record SdxlModelLoaderNode : IInvokeAINode
{
    public string Id { get; init; } = "sdxl_model_loader";
    public string Type { get; init; } = "sdxl_model_loader";
    [JsonPropertyName("model")]
    public InvokeAIModel Model { get; init; } = new();
    [JsonPropertyName("vae_precision")]
    public string VaePrecision { get; init; } = "fp32";
}

public record SdxlLoraLoaderNode : IInvokeAINode
{
    public string Id { get; init; } = "";
    public string Type { get; init; } = "sdxl_lora_loader";
    [JsonPropertyName("lora")]
    public InvokeAIModel Lora { get; init; } = new();
    [JsonPropertyName("weight")]
    public double Weight { get; init; }
    [JsonPropertyName("submodels")]
    public List<string> Submodels { get; init; } = new() { "unet", "text_encoder", "text_encoder_2" };
}

public record SdxlCompelPromptNode : IInvokeAINode
{
    public string Id { get; init; } = "";
    public string Type { get; init; } = "sdxl_compel_prompt";
}

public record InvokeAIImageField
{
    [JsonPropertyName("image_name")]
    public string ImageName { get; init; } = "";
}

public record SpandrelImageToImageAutoscaleNode : IInvokeAINode
{
    public string Id { get; init; } = "spandrel_upscale";
    public string Type { get; init; } = "spandrel_image_to_image_autoscale";
    [JsonPropertyName("image")]
    public InvokeAIImageField? Image { get; init; }
    [JsonPropertyName("image_to_image_model")]
    public InvokeAIModel? ImageToImageModel { get; init; }
    [JsonPropertyName("tile_size")]
    public int TileSize { get; init; } = 512;
    [JsonPropertyName("scale")]
    public double Scale { get; init; } = 4.0;
    [JsonPropertyName("fit_to_multiple_of_8")]
    public bool FitToMultipleOf8 { get; init; } = false;
}
