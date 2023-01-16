import os
import pandas as pd
import kaggle
import time
from datetime import timedelta
from typing import List


class _NotebookCrawler:

    source_name = str

    def __init__(self):
        self.directories = {
            'notebooks': f'data/{self.source_name}/raw_notebooks/',
            'metadata': f'data/{self.source_name}/notebooks_metadata/',
            'log': f'data/logs/',
            }
        self._add_abs_path_to_directories()
        self._make_directories()
        self.files = {
            'search_log': os.path.join(self.directories['log'], 'search.csv'),
            'download_log': os.path.join(
                self.directories['log'], 'download.csv'
                ),
            }

    def _add_abs_path_to_directories(self):
        for k, v in self.directories.items():
            self.directories[k] = os.path.join(os.path.dirname(__file__), v)

    def _make_directories(self):
        for d in self.directories.values():
            os.makedirs(d, exist_ok=True)


class KaggleNotebookCrawler(_NotebookCrawler):

    source_name = 'Kaggle'

    def search(self, query, page_range):
        """ Search Kaggle kernels using given query
        """
        kernels = []
        for page in range(1, page_range + 1):
            try:
                kernel_list = kaggle.api.kernels_list(search=query, page=page)
                print(f'Crawling page {page}')
                if len(kernel_list) == 0:
                    break
                else:
                    kernels.extend(kernel_list)
            # Skip the pages that cause ApiException
            except kaggle.rest.ApiException:
                continue

        # Extract the `title` and the `ref` of returned Kaggle kernels
        results = []
        for kernel in kernels:
            results.append(
                {
                    'query': query,
                    'title': kernel.title,
                    'kernel_ref': kernel.ref
                    }
                )

        print('\n')
        return pd.DataFrame(results)

    def download(self, notebook_ref):
        """ Download the kernels together with the metadata file

        Args:
            - notebook_ref: the ID used by Kaggle to denote one notebook.

        Return:
            - Boolean: Only True when the file is correctly downloaded or
              already exists.


        The notebook will be downloaded as 'dirname_basename' of
        `notebook_ref`.

        For example, given kernel_ref = 'buddhiniw/breast-cancer-prediction',
        there will be two files downloaded:
            - buddhiniw_breast-cancer-prediction.ipynb
            - buddhiniw_breast-cancer-prediction.json
        """
        if pd.isna(notebook_ref):
            print(f'[*NO REF] {notebook_ref}')
            return False

        download_path = self.directories['notebooks']
        file_name = os.path.dirname(notebook_ref) + '_' + os.path.basename(
            notebook_ref
            )
        # kaggle.api.kernels_pall downloads the nb to
        #  ('dl_notebook') and the metadata to
        # /path/kernel-metadata.json ('dl_metadata').
        files = {
            # notebook downloaded by Kaggle API (/path/<filename>.ipynb)
            'dl_notebook': os.path.join(
                download_path, os.path.basename(notebook_ref)
                ) + '.ipynb',
            # metadata downloaded by Kaggle API (/path/<filename>.ipynb)
            'dl_metadata': os.path.join(download_path, 'kernel-metadata.json'),
            # notebook destination (/path/<username>_<filename>.ipynb)
            'notebook': os.path.join(
                self.directories['notebooks'], file_name + '.ipynb'),
            # metadata destination (/path/<username>_<filename>.json)
            'metadata': os.path.join(
                self.directories['metadata'], file_name + '.json'),
            }

        # Check if the file is already downloaded
        if os.path.isfile(files['notebook']):
            print(f'[!!EXIST] {notebook_ref}')
            return True
        try:
            kaggle.api.kernels_pull(notebook_ref, download_path, metadata=True)
            print(f'[Pulling] {notebook_ref}')

            if not os.path.isfile(files['dl_notebook']):
                print(f'[***FAIL] {notebook_ref}')
                # It is very important to delete the metadata file,
                # otherwise the following downloading will fail
                os.remove(files['dl_metadata'])
                return False

            # Rename the notebook file
            try:
                os.rename(files['dl_notebook'], files['notebook'])
            except FileNotFoundError as err:
                print("Exception: ", err)
                return False

            # Rename the metadata file
            try:
                os.rename(files['dl_metadata'], files['metadata'])
            except FileNotFoundError as err:
                print("Exception: ", err)
                return False
        except Exception as err:
            print("Exception: ", err)
            return False
        return True

    def bulk_search(self, queries, page_range):
        """' Search for notebooks """
        df_notebooks = pd.DataFrame()
        # Search notebooks for each query
        start = time.time()
        for i, query in enumerate(queries):
            print(
                f'---------------- Query [{i + 1}]: {query} ----------------'
                )
            # To save the memory, we write the searching results to disk for
            # every 10 queries
            df_notebooks = pd.concat(
                [df_notebooks, self.search(query, page_range)]
                )
            df_notebooks.drop_duplicates(inplace=True)
            if (i + 1) % 10 == 0 or i + 1 == len(queries):
                # Update notebook search logs
                try:
                    search_logs = pd.read_csv(self.files['search_log'])
                except Exception as e:
                    print(e)
                    search_logs = pd.DataFrame(columns=df_notebooks.columns)

                if df_notebooks.empty:
                    search_all = search_logs
                else:
                    search_all = search_logs.merge(df_notebooks, how='outer')
                search_all.drop_duplicates(inplace=True)
                search_all.to_csv(self.files['search_log'], index=False)
                end = time.time()
                print(
                    f'>>>>> Saving {len(df_notebooks)} searching results to disk...'
                    )
                print(
                    f'>>>>> Time elapsed: {str(timedelta(seconds=int(end - start)))}\n\n'
                    )
                # Reset the notebooks after saving to the log file
                df_notebooks.drop(df_notebooks.index, inplace=True)
        return search_all

    def bulk_download(self, df_notebooks):
        """ Download a bunch of notebooks specified inside `df_notebooks`"""
        # Read notebook download logs and filter out the new notbooks to download
        try:
            download_logs = pd.read_csv(self.files['download_log'])
        except Exception as e:
            print(e)
            download_logs = pd.DataFrame(columns=df_notebooks.columns)

        merged = df_notebooks.merge(download_logs, how='left', indicator=True)
        new_notebooks = merged[merged['_merge'] == 'left_only'].drop(
            columns=['_merge']
            )
        new_notebooks.reset_index(inplace=True, drop=True)
        print(
            f'--------------------------- {len(new_notebooks)} new Notebooks --------------------------------'
            )
        print(f'{new_notebooks}')
        print(
            f'----------------------------------------------------------------------------\n\n'
            )

        # Download the notebooks and keep track of downloaded notebooks 
        start = time.time()
        downloaded_notebooks = pd.DataFrame()
        print(f'------------------ {0} - {49}  notebooks -------------------')
        for j in range(len(new_notebooks)):
            # Download the notebooks
            kernel_ref = new_notebooks.iloc[j]['kernel_ref']
            if self.download(kernel_ref):
                downloaded_notebooks = pd.concat(
                    [downloaded_notebooks, new_notebooks.iloc[[j]]]
                    )

            if (j + 1) % 50 == 0 or j + 1 == len(new_notebooks):
                # Update notebook download logs for every 100 notebooks
                try:
                    download_logs = pd.read_csv(self.files['download_log'])
                except Exception as e:
                    print(e)
                    download_logs = pd.DataFrame(
                        columns=downloaded_notebooks.columns
                        )

                print(
                    f'downloaded_notebooks.empty: {downloaded_notebooks.empty}'
                    )

                if downloaded_notebooks.empty:
                    download_all = download_logs
                else:
                    download_all = download_logs.merge(
                        downloaded_notebooks, how='outer'
                        )
                download_all.drop_duplicates(inplace=True)
                # Save notebook names, IDs etc to .csv file. 
                download_all.to_csv(self.files['download_log'], index=False)
                end = time.time()
                print(
                    f'\n\n>>>>> Saving {len(downloaded_notebooks)} downloaded results to disk...'
                    )
                print(
                    f'>>>>> Time elapsed: {str(timedelta(seconds=int(end - start)))}\n\n'
                    )
                # Reset downloaded_notebooks
                downloaded_notebooks.drop(
                    downloaded_notebooks.index, inplace=True
                    )
                print(
                    f'------------------ {j + 1} - {j + 50}  notebooks -------------------'
                    )

        return True

    def crawl(self, queries: List[str], page_range: int):
        """ Search and download notebooks using given queries

        The notebooks will be downloads to disk

        :param queries: search queries
        :param page_range: number of pages to crawl for each query
        """
        df_notebooks = self.bulk_search(queries, page_range)
        self.bulk_download(df_notebooks)


def main():
    # Read queries
    df_queries = pd.read_csv(
        os.path.join(
            os.path.dirname(__file__),
            'data_sources/kaggle_crawler_queries.csv'
            )
        )
    queries = df_queries['queries'].values

    crawler = KaggleNotebookCrawler()
    crawler.crawl(queries, page_range=1)


if __name__ == '__main__':
    main()