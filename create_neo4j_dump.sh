#!/bin/bash
# Create Neo4j database dump for cloud migration

DUMP_DIR="$(pwd)/neo4j_dumps"
DUMP_FILE="canada-census-$(date +%Y%m%d).dump"
USER_ID=$(id -u)
GROUP_ID=$(id -g)

mkdir -p "$DUMP_DIR"

echo "Creating Neo4j database dump..."
docker run --rm \
  --volumes-from neo4j-canada-census \
  -v "$DUMP_DIR:/dumps" \
  --user root \
  neo4j:community \
  bash -c "neo4j-admin database dump neo4j --to-path=/dumps && chown -R $USER_ID:$GROUP_ID /dumps"

if [ $? -eq 0 ]; then
    mv "$DUMP_DIR/neo4j.dump" "$DUMP_DIR/$DUMP_FILE"
    echo ""
    echo "✓ Database dump created successfully!"
    ls -lh "$DUMP_DIR/$DUMP_FILE"
else
    echo "✗ Dump failed"
    exit 1
fi
