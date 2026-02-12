import pandas as pd
from ydata_profiling import ProfileReport
import sys
from pathlib import Path


def generate_profile(parquet_path):
    """
    Generate a data profiling report for a parquet file.
    
    Args:
        parquet_path: Path to the parquet file to profile
    """
    parquet_path = Path(parquet_path)
    
    if not parquet_path.exists():
        print(f"Error: File not found - {parquet_path}")
        return
    
    # Load the Parquet file into a DataFrame
    df = pd.read_parquet(parquet_path)
    
    # Derive layer name and output filename from path
    layer_name = parquet_path.parent.name.capitalize()
    layer_folder = parquet_path.parent
    file_name = parquet_path.stem
    output_file = layer_folder / f"{layer_name.lower()}_data_profile.html"
    
    # Generate a profiling report
    title = f"{layer_name} Layer Data Profiling - {file_name}"
    profile = ProfileReport(df, title=title, explorative=True)
    
    # Save the report to an HTML file
    profile.to_file(output_file)
    
    print(f"✓ Profiling report saved as {output_file}")
    print(f"  Shape: {df.shape[0]} rows × {df.shape[1]} columns")


if __name__ == "__main__":
    # Usage: uv run profiling.py [parquet_path]
    # Examples:
    #   uv run profiling.py bronze/bronze_event.parquet
    #   uv run profiling.py gold/entity_metrics.parquet
    
    if len(sys.argv) > 1:
        parquet_path = sys.argv[1]
    else:
        # Default example: Silver layer sample file
        parquet_path = "silver/silver_event.parquet"
        print(f"No file specified. Using example: {parquet_path}\n")
    
    generate_profile(parquet_path)
