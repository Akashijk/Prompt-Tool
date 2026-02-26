using Avalonia;
using Avalonia.Xaml.Interactivity;
using AvaloniaEdit;
using Avalonia.Data;

namespace PromptTool.Behaviors;

public class TextEditorBindingBehavior : Behavior<TextEditor>
{
    public static readonly StyledProperty<string> TextProperty =
        AvaloniaProperty.Register<TextEditorBindingBehavior, string>(nameof(Text), defaultBindingMode: BindingMode.TwoWay);

    public string Text
    {
        get => GetValue(TextProperty);
        set => SetValue(TextProperty, value);
    }

    protected override void OnAttached()
    {
        base.OnAttached();
        if (AssociatedObject != null)
        {
            AssociatedObject.Document.TextChanged += Document_TextChanged;
            // Set initial text from ViewModel to Editor
            AssociatedObject.Text = Text;
        }
    }

    protected override void OnDetaching()
    {
        base.OnDetaching();
        if (AssociatedObject != null)
        {
            AssociatedObject.Document.TextChanged -= Document_TextChanged;
        }
    }

    private void Document_TextChanged(object? sender, System.EventArgs e)
    {
        // Update ViewModel's Text property when Editor's text changes
        if (AssociatedObject != null && Text != AssociatedObject.Text)
        {
            Text = AssociatedObject.Text;
        }
    }

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);
        if (change.Property == TextProperty && AssociatedObject != null)
        {
            // Update Editor's text when ViewModel's Text property changes
            if (AssociatedObject.Text != Text)
            {
                AssociatedObject.Text = Text;
            }
        }
    }
}
